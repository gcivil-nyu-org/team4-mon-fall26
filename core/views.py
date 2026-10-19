from django.http import HttpResponse
from django.shortcuts import render


def home(request):
    """Landing page. Confirms the deployment is up."""
    return render(request, "core/home.html")


def health(request):
    """Plain-text health check, handy for load balancers and smoke tests."""
    return HttpResponse("ok", content_type="text/plain")
