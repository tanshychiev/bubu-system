from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from .models import Service
from .forms import ServiceForm


@login_required
def service_list(request):
    services = Service.objects.all().order_by("-id")
    return render(request, "services/service_list.html", {"services": services})


@login_required
def service_detail(request, pk):
    service = get_object_or_404(Service, pk=pk)
    return render(request, "services/service_detail.html", {"service": service})


@login_required
def service_create(request):
    form = ServiceForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Service created.")
        return redirect("service_list")
    return render(request, "services/service_form.html", {"form": form, "title": "Create Service"})


@login_required
def service_update(request, pk):
    service = get_object_or_404(Service, pk=pk)
    form = ServiceForm(request.POST or None, instance=service)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Service updated.")
        return redirect("service_list")
    return render(request, "services/service_form.html", {"form": form, "title": "Edit Service"})


@login_required
def service_delete(request, pk):
    service = get_object_or_404(Service, pk=pk)
    if request.method == "POST":
        service.delete()
        messages.success(request, "Service deleted.")
        return redirect("service_list")
    return render(request, "services/service_confirm_delete.html", {"service": service})