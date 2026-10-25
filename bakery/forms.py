from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.core.exceptions import ValidationError

from .models import CustomerAddress, User


class RegistrationForm(UserCreationForm):
    class Meta:
        model = User
        fields = ("email", "name", "phone")


class CheckoutForm(forms.Form):
    fulfillment_type = forms.ChoiceField(choices=(
        ("DELIVERY", "Delivery"),
        ("PICKUP", "Branch pickup"),
    ))
    delivery_address = forms.CharField(required=False, max_length=1000, widget=forms.Textarea)
    scheduled_date = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    scheduled_time_slot = forms.CharField(required=False, max_length=80)
    slicing_preference = forms.CharField(required=False, max_length=40, initial="Unsliced")
    saved_address = forms.ChoiceField(required=False)

    def clean(self):
        cleaned_data = super().clean()
        address_id = cleaned_data.pop("saved_address", "")
        if address_id:
            try:
                saved = CustomerAddress.objects.get(pk=address_id, user=self.user)
            except CustomerAddress.DoesNotExist as exc:
                raise ValidationError("Choose one of your saved addresses.") from exc
            cleaned_data["delivery_address"] = (
                f"{saved.recipient_name}, {saved.phone}, {saved.address}, "
                f"{saved.city}, {saved.state}"
            )
        return cleaned_data

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        self.fields["saved_address"].choices = [
            ("", "Enter a delivery address"),
            *(
                (str(address.pk), f"{address.label or address.recipient_name} — {address.city}")
                for address in user.addresses.all()
            ),
        ] if user and user.is_authenticated else [("", "Enter a delivery address")]


class CustomerAddressForm(forms.ModelForm):
    class Meta:
        model = CustomerAddress
        fields = ("label", "recipient_name", "phone", "address", "city", "state", "is_default")
