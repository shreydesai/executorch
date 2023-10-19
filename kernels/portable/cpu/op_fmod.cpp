/*
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 * All rights reserved.
 *
 * This source code is licensed under the BSD-style license found in the
 * LICENSE file in the root directory of this source tree.
 */

#include <cmath>

#include <executorch/kernels/portable/cpu/scalar_utils.h>
#include <executorch/kernels/portable/cpu/util/broadcast_util.h>
#include <executorch/kernels/portable/cpu/util/functional_util.h>
#include <executorch/runtime/kernel/kernel_includes.h>

namespace torch {
namespace executor {
namespace native {

using Tensor = exec_aten::Tensor;

Tensor& fmod_Tensor_out(
    RuntimeContext& ctx,
    const Tensor& a,
    const Tensor& b,
    Tensor& out) {
  (void)ctx;

  // Determine output size and resize for dynamic shapes
  resize_to_broadcast_target_size(a, b, out);

  ScalarType a_type = a.scalar_type();
  ScalarType b_type = b.scalar_type();
  ScalarType common_type = promoteTypes(a_type, b_type);
  ScalarType out_type = out.scalar_type();

  ET_CHECK(canCast(common_type, out_type));

  ET_SWITCH_REAL_TYPES_AND(
      Bool, a_type, ctx, "fmod.Tensor_out", CTYPE_A, [&]() {
        ET_SWITCH_REAL_TYPES_AND(
            Bool, b_type, ctx, "fmod.Tensor_out", CTYPE_B, [&]() {
              ET_SWITCH_REAL_TYPES(
                  common_type, ctx, "fmod.Tensor_out", CTYPE_IN, [&]() {
                    ET_SWITCH_REAL_TYPES(
                        out_type, ctx, "fmod.Tensor_out", CTYPE_OUT, [&]() {
                          apply_binary_elementwise_fn<
                              CTYPE_A,
                              CTYPE_B,
                              CTYPE_OUT>(
                              [common_type](
                                  const CTYPE_A val_a, const CTYPE_B val_b) {
                                if (isIntegralType(
                                        common_type, /*includeBool=*/true)) {
                                  ET_CHECK(val_b != 0);
                                }
                                CTYPE_IN a_casted =
                                    static_cast<CTYPE_IN>(val_a);
                                CTYPE_IN b_casted =
                                    static_cast<CTYPE_IN>(val_b);
                                CTYPE_IN value = std::fmod(a_casted, b_casted);

                                return static_cast<CTYPE_OUT>(value);
                              },
                              a,
                              b,
                              out);
                        });
                  });
            });
      });

  return out;
}

Tensor& fmod_Scalar_out(
    RuntimeContext& ctx,
    const Tensor& a,
    const Scalar& b,
    Tensor& out) {
  (void)ctx;

  // Determine output size and resize for dynamic shapes
  ET_CHECK(resize_tensor(out, a.sizes()) == Error::Ok);

  ScalarType a_type = a.scalar_type();
  ScalarType b_type = utils::get_scalar_dtype(b);
  ScalarType common_type = utils::promote_type_with_scalar(a_type, b);
  ScalarType out_type = out.scalar_type();

  ET_CHECK(canCast(common_type, out_type));

  ET_SWITCH_REAL_TYPES_AND(
      Bool, a_type, ctx, "fmod.Scalar_out", CTYPE_A, [&]() {
        ET_SWITCH_SCALAR_OBJ_TYPES(
            b_type, ctx, "fmod.Scalar_out", CTYPE_B, [&]() {
              CTYPE_B val_b = 0;
              ET_EXTRACT_SCALAR(b, val_b);
              ET_SWITCH_REAL_TYPES(
                  common_type, ctx, "fmod.Scalar_out", CTYPE_IN, [&]() {
                    if (isIntegralType(common_type, /*includeBool=*/true)) {
                      ET_CHECK(val_b != 0);
                    }
                    ET_SWITCH_REAL_TYPES(
                        out_type, ctx, "fmod.Scalar_out", CTYPE_OUT, [&]() {
                          apply_unary_map_fn(
                              [val_b](const CTYPE_A val_a) {
                                CTYPE_IN a_casted =
                                    static_cast<CTYPE_IN>(val_a);
                                CTYPE_IN b_casted =
                                    static_cast<CTYPE_IN>(val_b);
                                CTYPE_IN value = std::fmod(a_casted, b_casted);

                                return static_cast<CTYPE_OUT>(value);
                              },
                              a.const_data_ptr<CTYPE_A>(),
                              out.mutable_data_ptr<CTYPE_OUT>(),
                              out.numel());
                        });
                  });
            });
      });

  return out;
}

} // namespace native
} // namespace executor
} // namespace torch