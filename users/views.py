from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from django.contrib.auth.models import User, Group, Permission
from django.contrib.auth.decorators import login_required, permission_required
from django.db.models import Q

from .forms import UserForm, RoleForm
from .models import StaffProfile


def user_login(request):
    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")

        user = authenticate(request, username=username, password=password)

        if user:
            login(request, user)
            return redirect("dashboard")

        messages.error(request, "Wrong username or password.")

    return render(request, "users/login.html")


def user_logout(request):
    logout(request)
    return redirect("login")


@login_required
@permission_required("auth.view_user", raise_exception=True)
def user_list(request):
    q = request.GET.get("q", "").strip()

    users = (
        User.objects
        .all()
        .prefetch_related("groups")
        .select_related("staff_profile", "staff_profile__branch")
        .order_by("-id")
    )

    if q:
        users = users.filter(
            Q(username__icontains=q)
            | Q(email__icontains=q)
            | Q(first_name__icontains=q)
            | Q(last_name__icontains=q)
            | Q(groups__name__icontains=q)
            | Q(staff_profile__branch__name__icontains=q)
        ).distinct()

    return render(request, "users/user_list.html", {
        "users": users,
        "q": q,
    })


@login_required
@permission_required("auth.add_user", raise_exception=True)
def user_create(request):
    if request.method == "POST":
        form = UserForm(request.POST)

        if form.is_valid():
            user = form.save()
            messages.success(
                request,
                f"User {user.username} created successfully.",
            )
            return redirect("user_list")
    else:
        form = UserForm()

    return render(request, "users/user_form.html", {
        "form": form,
        "title": "Add User",
    })


@login_required
@permission_required("auth.change_user", raise_exception=True)
def user_edit(request, pk):
    user_obj = get_object_or_404(User, pk=pk)

    if request.method == "POST":
        form = UserForm(request.POST, instance=user_obj)

        if form.is_valid():
            user = form.save()
            messages.success(
                request,
                f"User {user.username} updated successfully.",
            )
            return redirect("user_list")
    else:
        form = UserForm(instance=user_obj)

    return render(request, "users/user_form.html", {
        "form": form,
        "title": "Edit User",
        "user_obj": user_obj,
    })


@login_required
@permission_required("auth.change_user", raise_exception=True)
def user_toggle_active(request, pk):
    user_obj = get_object_or_404(User, pk=pk)

    if user_obj == request.user:
        messages.error(request, "You cannot deactivate your own account.")
        return redirect("user_list")

    user_obj.is_active = not user_obj.is_active
    user_obj.save(update_fields=["is_active"])

    messages.success(request, "User status updated.")
    return redirect("user_list")


@login_required
@permission_required("auth.view_group", raise_exception=True)
def role_list(request):
    q = request.GET.get("q", "").strip()

    roles = Group.objects.all().prefetch_related("permissions").order_by("name")

    if q:
        roles = roles.filter(
            Q(name__icontains=q)
            | Q(permissions__name__icontains=q)
            | Q(permissions__codename__icontains=q)
        ).distinct()

    return render(request, "users/role_list.html", {
        "roles": roles,
        "q": q,
        "total_roles": roles.count(),
    })


@login_required
@permission_required("auth.add_group", raise_exception=True)
def role_create(request):
    if request.method == "POST":
        form = RoleForm(request.POST)

        if form.is_valid():
            form.save()
            messages.success(request, "Role created successfully.")
            return redirect("role_list")
    else:
        form = RoleForm()

    return render(request, "users/role_form.html", {
        "form": form,
        "title": "Add Role",
    })


@login_required
@permission_required("auth.change_group", raise_exception=True)
def role_edit(request, pk):
    role = get_object_or_404(Group, pk=pk)

    if request.method == "POST":
        form = RoleForm(request.POST, instance=role)

        if form.is_valid():
            form.save()
            messages.success(request, "Role updated successfully.")
            return redirect("role_list")
    else:
        form = RoleForm(instance=role)

    return render(request, "users/role_form.html", {
        "form": form,
        "title": "Edit Role",
        "role": role,
    })


@login_required
@permission_required("auth.delete_group", raise_exception=True)
def role_delete(request, pk):
    role = get_object_or_404(Group, pk=pk)

    if request.method == "POST":
        role.delete()
        messages.success(request, "Role deleted successfully.")
        return redirect("role_list")

    return render(request, "users/role_delete.html", {
        "role": role,
    })


@login_required
@permission_required("auth.view_permission", raise_exception=True)
def permission_list(request):
    q = request.GET.get("q", "").strip()

    permissions = Permission.objects.select_related("content_type").order_by(
        "content_type__app_label",
        "content_type__model",
        "codename",
    )

    if q:
        permissions = permissions.filter(
            Q(name__icontains=q)
            | Q(codename__icontains=q)
            | Q(content_type__app_label__icontains=q)
            | Q(content_type__model__icontains=q)
        )

    return render(request, "users/permission_list.html", {
        "permissions": permissions,
        "q": q,
    })