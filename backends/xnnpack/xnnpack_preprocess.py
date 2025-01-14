# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

import copy

import logging
from dataclasses import dataclass
from typing import Dict, final, List

import torch
from executorch.backends.xnnpack.operators.node_visitor import get_node_visitors

from executorch.backends.xnnpack.passes import XNNPACKPassManager
from executorch.backends.xnnpack.passes.convert_to_linear import ConvertToLinearPass
from executorch.backends.xnnpack.passes.tag_implicit_q_dq_pass import TagImplicitQDqPass

from executorch.backends.xnnpack.serialization.xnnpack_graph_schema import (
    ConstantDataOffset,
    XNNGraph,
)
from executorch.backends.xnnpack.serialization.xnnpack_graph_serialize import (
    serialize_xnnpack_binary,
)
from executorch.backends.xnnpack.utils.utils import is_param_node

from executorch.backends.xnnpack.utils.xnnpack_constants import (
    XNN_VALUE_FLAG_EXTERNAL_INPUT,
    XNN_VALUE_FLAG_EXTERNAL_OUTPUT,
)

from executorch.exir.backend.backend_details import (
    BackendDetails,
    CompileSpec,
    PreprocessResult,
)
from executorch.exir.verification.verifier import EXIREdgeDialectVerifier
from torch.export.exported_program import ExportedProgram

DEFAULT_DEBUG_HANDLE = 65535

logger = logging.getLogger(__name__)
logger.setLevel(logging.WARNING)


@dataclass
class ExternalMeta:
    external_id: int
    io_type: int


def generate_node_to_external_map(
    exported_program: ExportedProgram,
    edge_graph_module: torch.fx.GraphModule,
) -> Dict[torch.fx.Node, ExternalMeta]:
    node_to_external_map = {}
    for node in edge_graph_module.graph.nodes:
        # The order in which we visit the placeholder node is same as the *args
        # order for the forward(*args) signature for this gm. Using the order of
        # the nodes as external_id to extract the right arg from *args at runtime
        #
        # Removing parameters/buffers since they will disappear from the signature
        # at runtime
        if node.op == "placeholder" and not is_param_node(exported_program, node):
            node_to_external_map[node] = ExternalMeta(
                external_id=len(node_to_external_map),
                io_type=XNN_VALUE_FLAG_EXTERNAL_INPUT,
            )
    for node in edge_graph_module.graph.nodes:
        if node.op == "output":
            for output_nodes in node.args:
                for output_node in output_nodes:
                    node_to_external_map[output_node] = ExternalMeta(
                        external_id=len(node_to_external_map),
                        io_type=XNN_VALUE_FLAG_EXTERNAL_OUTPUT,
                    )
    return node_to_external_map


@final
class XnnpackBackend(BackendDetails):
    @staticmethod
    def preprocess(
        edge_program: ExportedProgram,
        compile_specs: List[CompileSpec],
    ) -> PreprocessResult:
        ep = copy.deepcopy(edge_program)
        # Need to wrap EP here because xnnpack does addmm to linear
        # transforms. This makes resulting graph not aten compliant
        # as aten.linear is not a core aten op.
        # Ideal fix would be to have XNNPACK verifier that bypass
        # most checks but the base Verifier itself has some strict changes
        # and to bypass those, we would basically copy what EdgeDialectVerifier
        # does. So for now instead of copy pasting that, just instantiate
        # EdgeDialectVerifier, but disable it.
        # TODO (task link) to implement NullVerifier or something similar
        ep = ExportedProgram(
            root=ep.graph_module,
            graph=ep.graph,
            graph_signature=ep.graph_signature,
            state_dict=ep.state_dict,
            range_constraints=ep.range_constraints,
            module_call_graph=copy.deepcopy(ep.module_call_graph),
            example_inputs=ep.example_inputs,
            verifier=EXIREdgeDialectVerifier(
                check_edge_ops=False, enable=False, class_only=True
            ),
            constants=ep.constants,
        )

        passes = []
        for spec in compile_specs:
            if spec.key == "dqlinear_partitioner":
                passes.append(ConvertToLinearPass)
                passes.append(TagImplicitQDqPass)

        passes = passes if len(passes) > 0 else None
        # XNNPACK Delegate Specific Passes
        ep = XNNPACKPassManager(ep, passes=passes).transform()
        graph_module = ep.graph_module

        node_to_external_map = generate_node_to_external_map(ep, graph_module)

        # TODO retrace the graph module to lift the new params may have
        # been added to the graph in passes

        vals_to_ids = {}
        xnnpack_graph = XNNGraph(
            version="0",
            xnodes=[],
            xvalues=[],
            num_externs=len(node_to_external_map),
            input_ids=[],
            output_ids=[],
            constant_data=[ConstantDataOffset(0, 0)],
        )

        constant_data_bytes = bytearray()
        node_visitors = get_node_visitors(ep, node_to_external_map, constant_data_bytes)

        for node in graph_module.graph.nodes:
            if node.op == "call_function":
                logger.info(f"Visiting: {node}, {node.target.__name__}")
                if node.target.__name__ in node_visitors:
                    node_visitors[node.target.__name__].define_node(
                        node,
                        xnnpack_graph,
                        vals_to_ids,
                        node.meta.get("debug_handle", DEFAULT_DEBUG_HANDLE),
                    )
                else:
                    raise RuntimeError(
                        f"For {node}, {node.op}:{node.target.__name__} is not supported in XNNPACK Delegate"
                    )
            elif node.op in [
                "get_attr",
                "placeholder",
                "output",
            ]:
                continue
            else:
                raise RuntimeError(f"{node.op} is not supported in XNNPACK")
        return PreprocessResult(
            processed_bytes=serialize_xnnpack_binary(
                xnnpack_graph, constant_data_bytes
            ),
            debug_handle_map={},
        )
