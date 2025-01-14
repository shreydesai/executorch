# Copyright (c) Qualcomm Innovation Center, Inc.
# All rights reserved
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

import json
import os
import tempfile

import pkg_resources
from executorch.backends.qualcomm.serialization.qnn_compile_spec_schema import (
    QnnExecuTorchOptions,
)
from executorch.exir._serialize._dataclass import _DataclassEncoder

from executorch.exir._serialize._flatbuffer import _flatc_compile


def convert_to_flatbuffer(qnn_executorch_options: QnnExecuTorchOptions) -> bytes:
    qnn_executorch_options_json = json.dumps(
        qnn_executorch_options, cls=_DataclassEncoder
    )
    with tempfile.TemporaryDirectory() as d:
        schema_path = os.path.join(d, "schema.fbs")
        with open(schema_path, "wb") as schema_file:
            schema_file.write(pkg_resources.resource_string(__name__, "schema.fbs"))
        json_path = os.path.join(d, "schema.json")
        with open(json_path, "wb") as json_file:
            json_file.write(qnn_executorch_options_json.encode("ascii"))

        _flatc_compile(d, schema_path, json_path)
        output_path = os.path.join(d, "schema.bin")
        with open(output_path, "rb") as output_file:
            return output_file.read()
