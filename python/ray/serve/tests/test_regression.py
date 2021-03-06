import gc

import numpy as np
import requests

import ray
from ray import serve


def test_np_in_composed_model(serve_instance):
    client = serve_instance

    # https://github.com/ray-project/ray/issues/9441
    # AttributeError: 'bytes' object has no attribute 'readonly'
    # in cloudpickle _from_numpy_buffer

    def sum_model(request):
        return np.sum(request.query_params["data"])

    class ComposedModel:
        def __init__(self):
            client = serve.connect()
            self.model = client.get_handle("sum_model")

        async def __call__(self, _request):
            data = np.ones((10, 10))
            result = await self.model.remote(data=data)
            return result

    client.create_backend("sum_model", sum_model)
    client.create_endpoint("sum_model", backend="sum_model")
    client.create_backend("model", ComposedModel)
    client.create_endpoint(
        "model", backend="model", route="/model", methods=["GET"])

    result = requests.get("http://127.0.0.1:8000/model")
    assert result.status_code == 200
    assert result.json() == 100.0


def test_backend_worker_memory_growth(serve_instance):
    # https://github.com/ray-project/ray/issues/12395
    client = serve_instance

    def gc_unreachable_objects(starlette_request):
        gc.set_debug(gc.DEBUG_SAVEALL)
        gc.collect()
        return len(gc.garbage)

    client.create_backend("model", gc_unreachable_objects)
    client.create_endpoint("model", backend="model", route="/model")

    handle = client.get_handle("model")

    for _ in range(10):
        result = requests.get("http://127.0.0.1:8000/model")
        assert result.status_code == 200
        num_unreachable_objects = result.json()
        assert num_unreachable_objects == 0

    for _ in range(10):
        num_unreachable_objects = ray.get(handle.remote())
        assert num_unreachable_objects == 0


if __name__ == "__main__":
    import sys
    import pytest
    sys.exit(pytest.main(["-v", "-s", __file__]))
