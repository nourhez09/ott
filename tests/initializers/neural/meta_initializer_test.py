# Copyright OTT-JAX
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
from typing import Optional

import pytest

import jax
import jax.numpy as jnp

from flax import linen as nn

from ott.geometry import pointcloud
from ott.initializers.neural import meta_initializer as meta_init
from ott.problems.linear import linear_problem
from ott.solvers.linear import sinkhorn


class MetaMLP(nn.Module):
  potential_size: int
  num_hidden_units: int = 512
  num_hidden_layers: int = 3

  @nn.compact
  def __call__(self, z: jnp.ndarray) -> jnp.ndarray:
    for _ in range(self.num_hidden_layers):
      z = nn.relu(nn.Dense(self.num_hidden_units)(z))
    return nn.Dense(self.potential_size)(z)


def create_ot_problem(
    rng: jax.Array,
    n: int,
    m: int,
    d: int,
    epsilon: float = 1e-2,
    batch_size: Optional[int] = None
) -> linear_problem.LinearProblem:
  # define ot problem
  x_rng, y_rng = jax.random.split(rng)
  mu_a = jnp.array([-1.0, 1.0]) * 5
  mu_b = jnp.array([0.0, 0.0])
  x = jax.random.normal(x_rng, (n, d)) + mu_a
  y = jax.random.normal(y_rng, (m, d)) + mu_b
  geom = pointcloud.PointCloud(x, y, epsilon=epsilon, batch_size=batch_size)
  return linear_problem.LinearProblem(geom=geom)


@pytest.mark.fast()
class TestMetaInitializer:

  @pytest.mark.parametrize("lse_mode", [True, False])
  def test_meta_initializer(self, rng: jax.Array, lse_mode: bool):
    """Tests Meta initializer"""
    n, m, d = 32, 30, 2
    epsilon = 1e-2

    ot_problem = create_ot_problem(rng, n, m, d, epsilon=epsilon, batch_size=3)

    # run sinkhorn
    solver = sinkhorn.Sinkhorn(lse_mode=lse_mode, max_iterations=3000)
    sink_out = jax.jit(solver)(ot_problem)

    # overfit the initializer to the problem.
    meta_model = MetaMLP(n)
    meta_initializer = meta_init.MetaInitializer(ot_problem.geom, meta_model)
    for _ in range(50):
      _, _, meta_initializer.state = meta_initializer.update(
          meta_initializer.state, a=ot_problem.a, b=ot_problem.b
      )

    solver = sinkhorn.Sinkhorn(
        initializer=meta_initializer, lse_mode=lse_mode, max_iterations=3000
    )
    meta_out = jax.jit(solver)(ot_problem)

    # check initializer is better
    if lse_mode:
      assert sink_out.converged
      assert meta_out.converged
      assert sink_out.n_iters > meta_out.n_iters
    else:
      assert sink_out.n_iters >= meta_out.n_iters
