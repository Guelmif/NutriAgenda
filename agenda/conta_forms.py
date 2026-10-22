from django import forms
from django.contrib.auth.forms import PasswordChangeForm


class AlterarSenhaForm(PasswordChangeForm):
    def clean_new_password1(self):
        password = self.cleaned_data["new_password1"]
        if self.user.check_password(password):
            raise forms.ValidationError(
                "A nova senha precisa ser diferente da senha atual.",
                code="password_unchanged",
            )
        return password
