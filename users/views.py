from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from django.contrib.auth.models import User, Group, Permission
from django.contrib.auth.decorators import login_required, permission_required
from django.db.models import Q
from django.db import transaction
from django.http import HttpResponseForbidden, HttpResponseNotAllowed
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from datetime import timedelta
from io import BytesIO
from hashlib import sha256
import secrets
import base64
import qrcode

from .forms import UserForm, RoleForm
from .models import StaffProfile, LoginQRToken


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

@login_required
@permission_required("auth.change_user", raise_exception=True)
@require_POST
def generate_user_login_qr(request, pk):
    if not request.user.is_superuser:
        return HttpResponseForbidden("Only administrators may issue QR logins.")
    target = get_object_or_404(User, pk=pk, is_active=True)
    if target.is_superuser:
        return HttpResponseForbidden("QR enrollment is not allowed for superuser accounts.")
    raw = secrets.token_urlsafe(32)
    hashed = sha256(raw.encode("utf-8")).hexdigest()
    with transaction.atomic():
        LoginQRToken.objects.filter(user=target, used_at__isnull=True, revoked_at__isnull=True).update(revoked_at=timezone.now())
        LoginQRToken.objects.create(
            user=target, token_hash=hashed, created_by=request.user,
            expires_at=timezone.now() + timedelta(hours=24),
        )
    url = request.build_absolute_uri(reverse("redeem_login_qr", args=[raw]))
    img = qrcode.make(url)
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    qr_image = base64.b64encode(buffer.getvalue()).decode("ascii")
    response = render(request, "users/login_qr_issued.html", {
        "target": target, "qr_image": qr_image, "login_url": url,
        "staff_options": User.objects.filter(is_active=True, is_superuser=False).order_by("username"),
    })
    response["Cache-Control"] = "no-store"
    response["Referrer-Policy"] = "same-origin"
    return response


def redeem_login_qr(request, token):
    token_hash = sha256(token.encode("utf-8")).hexdigest()

    def _token_context(record):
        now = timezone.now()
        if record is None:
            return {
                "is_valid": False,
                "status_label": "Invalid QR",
                "reason": "This login QR could not be found.",
            }
        if record.user.is_superuser:
            return {
                "is_valid": False,
                "status_label": "Unavailable",
                "reason": "This QR code cannot be used for this account.",
            }
        if not record.user.is_active:
            return {
                "is_valid": False,
                "status_label": "Inactive Account",
                "reason": "This staff account is not active.",
            }
        if record.revoked_at is not None:
            return {
                "is_valid": False,
                "status_label": "Replaced QR",
                "reason": "A newer login QR has already been generated for this staff account.",
            }
        if record.used_at is not None:
            return {
                "is_valid": False,
                "status_label": "Already Used",
                "reason": "This login QR has already been used successfully.",
            }
        if record.expires_at <= now:
            return {
                "is_valid": False,
                "status_label": "Expired",
                "reason": "This login QR has expired. Please ask the admin to generate a new one.",
            }

        remaining = record.expires_at - now
        total_seconds = max(0, int(remaining.total_seconds()))
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        if hours and minutes:
            remaining_text = f"{hours}h {minutes}m left"
        elif hours:
            remaining_text = f"{hours}h left"
        else:
            remaining_text = f"{max(1, minutes)}m left"

        display_name = (record.user.get_full_name() or record.user.username).strip()
        return {
            "is_valid": True,
            "status_label": "Ready to Login",
            "reason": "",
            "target_user": record.user,
            "display_name": display_name,
            "expires_at": record.expires_at,
            "remaining_text": remaining_text,
            "issued_by": record.created_by,
        }

    record = LoginQRToken.objects.select_related("user", "created_by").filter(token_hash=token_hash).first()

    if request.method == "GET":
        ctx = {"token": token, **_token_context(record)}
        response = render(request, "users/login_qr_redeem.html", ctx)
        response["Cache-Control"] = "no-store"
        response["Referrer-Policy"] = "same-origin"
        return response

    if request.method != "POST":
        return HttpResponseNotAllowed(["GET", "POST"])

    with transaction.atomic():
        record = (
            LoginQRToken.objects.select_for_update()
            .select_related("user", "created_by")
            .filter(token_hash=token_hash)
            .first()
        )
        ctx = _token_context(record)
        if not ctx.get("is_valid"):
            return render(request, "users/login_qr_invalid.html", ctx, status=400)
        record.used_at = timezone.now()
        record.save(update_fields=["used_at"])
        user = record.user

    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    request.session.set_expiry(365 * 24 * 60 * 60)
    return redirect("dashboard")
