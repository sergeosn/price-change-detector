import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("model", ["product", "domainrule", "pricechange"])
def test_changelist_opens(admin_client, model):
    response = admin_client.get(reverse(f"admin:tracker_{model}_changelist"))
    assert response.status_code == 200
