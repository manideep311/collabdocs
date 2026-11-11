import time


class RequestLoggingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        start = time.perf_counter()
        response = self.get_response(request)
        elapsed_ms = (time.perf_counter() - start) * 1000
        print(
            f'{request.method} {request.path} {response.status_code} {elapsed_ms:.1f}ms',
            flush=True,
        )
        return response
