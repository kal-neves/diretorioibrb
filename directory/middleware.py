from io import BytesIO

from django.http import HttpResponse
from django.utils.cache import add_never_cache_headers


class PhotoRequestLimit:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method == "POST" and request.path.startswith("/admin/directory/entry/"):
            body = request.read(2 * 1024 * 1024 + 1)
            if len(body) > 2 * 1024 * 1024:
                response = HttpResponse("O formulário excede o limite de 2 MiB. Reduza a foto.", status=413)
                add_never_cache_headers(response)
                return response
            # O parser multipart precisa reler o corpo já limitado antes de CSRF.
            request._body = body
            request._stream = BytesIO(body)
        return self.get_response(request)
