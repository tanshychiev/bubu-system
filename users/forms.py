from django import forms
from django.contrib.auth.models import User, Group, Permission

from inventory.models import Branch
from .models import StaffProfile


class UserForm(forms.ModelForm):
    password = forms.CharField(
        required=False,
        widget=forms.PasswordInput(attrs={
            "placeholder": "Leave blank to keep old password",
            "class": "form-control",
        }),
    )

    role = forms.ModelChoiceField(
        queryset=Group.objects.all().order_by("name"),
        required=False,
        empty_label="No role",
        widget=forms.Select(attrs={"class": "form-control"}),
    )

    branch = forms.ModelChoiceField(
        queryset=Branch.objects.filter(is_active=True).order_by("name"),
        required=False,
        empty_label="Select shop / branch",
        widget=forms.Select(attrs={"class": "form-control"}),
    )

    class Meta:
        model = User
        fields = [
            "username",
            "email",
            "first_name",
            "last_name",
            "is_active",
            "is_staff",
        ]

        widgets = {
            "username": forms.TextInput(attrs={"class": "form-control"}),
            "email": forms.EmailInput(attrs={"class": "form-control"}),
            "first_name": forms.TextInput(attrs={"class": "form-control"}),
            "last_name": forms.TextInput(attrs={"class": "form-control"}),
            "is_active": forms.CheckboxInput(),
            "is_staff": forms.CheckboxInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["branch"].queryset = Branch.objects.filter(
            is_active=True
        ).order_by("name")

        if self.instance and self.instance.pk:
            self.fields["role"].initial = self.instance.groups.first()

            try:
                profile = self.instance.staff_profile
                self.fields["branch"].initial = profile.branch
            except StaffProfile.DoesNotExist:
                pass

    def save(self, commit=True):
        user = super().save(commit=False)

        password = self.cleaned_data.get("password")
        if password:
            user.set_password(password)

        if commit:
            user.save()

            user.groups.clear()
            role = self.cleaned_data.get("role")
            if role:
                user.groups.add(role)

            branch = self.cleaned_data.get("branch")

            profile, created = StaffProfile.objects.get_or_create(user=user)
            profile.branch = branch
            profile.save(update_fields=["branch"])

        return user


class RoleForm(forms.ModelForm):
    permissions = forms.ModelMultipleChoiceField(
        queryset=Permission.objects.select_related("content_type").order_by(
            "content_type__app_label",
            "content_type__model",
            "codename",
        ),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    class Meta:
        model = Group
        fields = ["name", "permissions"]

        widgets = {
            "name": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Role name, example: Cashier",
            }),
        }