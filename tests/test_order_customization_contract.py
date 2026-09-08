import pytest
from pydantic import ValidationError
from app.protocol import PublicOrderCreateRequest


def test_unimplemented_options_are_rejected_instead_of_ignored():
    with pytest.raises(ValidationError) as error:
        PublicOrderCreateRequest(recipeId="latte", recipeVersion="1", options={"sugar": "NONE"})
    assert error.value.errors()[0]["type"] == "extra_forbidden"


def test_existing_order_contract_remains_valid():
    request = PublicOrderCreateRequest(recipeId="latte", recipeVersion="1", paymentMode="TEST_FREE")
    assert request.quantity == 1
