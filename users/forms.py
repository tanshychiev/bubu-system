from django import forms
from django.contrib.auth.models import User, Group, Permission

from inventory.models import Branch
from .models import StaffProfile


class UserForm(forms.ModelForm):
    password = forms.CharField(
        required=False,
        widget=forms.PasswordInput(attrs={
            "placeholder": "Leave blank to keep old password",
        }),
    )

    branch = forms.ModelChoiceField(
        queryset=Branch.objects.filter(is_active=True).order_by("name"),
        required=False,
        label="Staff Branch / Shop",
        help_text="For cashier/staff accounts. Admin can leave this blank.",
    )

    groups = forms.ModelMultipleChoiceField(
        queryset=Group.objects.all().order_by("name"),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    user_permissions = forms.ModelMultipleChoiceField(
        queryset=Permission.objects.select_related("content_type").order_by(
            "content_type__app_label",
            "content_type__model",
            "codename",
        ),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    class Meta:
        model = User
        fields = (
            "username",
            "first_name",
            "last_name",
            "email",
            "password",
            "is_active",
            "is_staff",
            "is_superuser",
            "groups",
            "user_permissions",
            "branch",
        )

        widgets = {
            "username": forms.TextInput(attrs={
                "placeholder": "Username",
            }),
            "first_name": forms.TextInput(attrs={
                "placeholder": "First name",
            }),
            "last_name": forms.TextInput(attrs={
                "placeholder": "Last name",
            }),
            "email": forms.EmailInput(attrs={
                "placeholder": "Email",
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["is_active"].initial = True

        for field_name, field in self.fields.items():
            if field_name not in ["groups", "user_permissions", "is_active", "is_staff", "is_superuser"]:
                field.widget.attrs.setdefault("class", "form-control")

        if self.instance and self.instance.pk:
            try:
                self.fields["branch"].initial = self.instance.staff_profile.branch
            except StaffProfile.DoesNotExist:
                self.fields["branch"].initial = None

    def clean(self):
        cleaned_data = super().clean()

        is_superuser = cleaned_data.get("is_superuser")
        branch = cleaned_data.get("branch")

        if not is_superuser and not branch:
            raise forms.ValidationError(
                "Normal staff/cashier must have a branch/shop assigned."
            )

        return cleaned_data

    def save(self, commit=True):
        password = self.cleaned_data.get("password")
        branch = self.cleaned_data.get("branch")

        user = super().save(commit=False)

        if password:
            user.set_password(password)

        if commit:
            user.save()
            self.save_m2m()

            profile, created = StaffProfile.objects.get_or_create(user=user)
            profile.branch = branch
            profile.save(update_fields=["branch", "updated_at"])

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
        fields = (
            "name",
            "permissions",
        )