"""Input constraints mirroring the ANNCSU OAS / anncsu-sdk validation rules.

The SDK validates payloads only in its CLI layer, so nothing checks them on the
service path before the server answers with opaque errors (e.g. error 100).
The facade input models therefore enforce the documented constraints up front:
Belfiore codcom format, OAS max lengths, DD/MM/YYYY calendar dates, metodo 1-4.
"""

import pytest
from pydantic import ValidationError

from app.models.workflows import (
    AggiornaCoordinateDaProgressivoAccessoInput,
    AggiornaCoordinateInput,
    CreaIndirizzoCompletoInput,
    RicercaIndirizzoInput,
    SopprimiOdonimoInput,
)

VALID = {
    CreaIndirizzoCompletoInput: {
        "codcom": "H501",
        "denom_odonimo": "ROMA",
        "dug": "VIA",
        "numero_civico": "42",
        "data_validita": "08/10/2024",
        "sezione_censimento": "580911010001",
    },
    AggiornaCoordinateInput: {
        "codcom": "H501",
        "denom_odonimo": "ROMA",
        "numero_civico": "42",
        "coordinata_x": "13.1022000",
        "coordinata_y": "41.8847600",
        "coordinata_z": "150",
        "metodo": "3",
    },
    AggiornaCoordinateDaProgressivoAccessoInput: {
        "codcom": "H501",
        "prognazacc": "1370588",
        "coordinata_x": "13.1022000",
        "coordinata_y": "41.8847600",
    },
    SopprimiOdonimoInput: {
        "codcom": "H501",
        "denom_odonimo": "ROMA",
        "data_soppressione": "08/10/2024",
    },
    RicercaIndirizzoInput: {
        "codcom": "H501",
        "denom_odonimo": "ROMA",
        "numero_civico": "42",
    },
}


@pytest.mark.parametrize("model", VALID)
def test_valid_inputs_are_accepted(model):
    assert model(**VALID[model])


@pytest.mark.parametrize(
    ("model", "field", "bad_value"),
    [
        # codcom: Belfiore format X999 (CodcomFormatError in the SDK)
        (CreaIndirizzoCompletoInput, "codcom", "h501"),
        (CreaIndirizzoCompletoInput, "codcom", "1234"),
        (CreaIndirizzoCompletoInput, "codcom", "H50"),
        (CreaIndirizzoCompletoInput, "codcom", "HH501"),
        (AggiornaCoordinateInput, "codcom", "h501"),
        (AggiornaCoordinateDaProgressivoAccessoInput, "codcom", "roma1"),
        (SopprimiOdonimoInput, "codcom", "501H"),
        (RicercaIndirizzoInput, "codcom", "h501"),
        # OAS max lengths (AccessoMaxLengthError in the SDK)
        (CreaIndirizzoCompletoInput, "numero_civico", "123456"),  # max 5
        (CreaIndirizzoCompletoInput, "sezione_censimento", "1" * 14),  # max 13
        (CreaIndirizzoCompletoInput, "denom_odonimo", "X" * 121),  # max 120
        (AggiornaCoordinateInput, "numero_civico", "123456"),
        (AggiornaCoordinateDaProgressivoAccessoInput, "prognazacc", "1" * 16),  # max 15
        (AggiornaCoordinateDaProgressivoAccessoInput, "coordinata_x", "1" * 13),  # max 12
        (AggiornaCoordinateDaProgressivoAccessoInput, "coordinata_z", "1" * 8),  # max 7
        (RicercaIndirizzoInput, "numero_civico", "123456"),
        # dates: valid DD/MM/YYYY calendar dates (InvalidDateFormatError in the SDK)
        (CreaIndirizzoCompletoInput, "data_validita", "2024-10-08"),
        (CreaIndirizzoCompletoInput, "data_validita", "31/02/2025"),
        (SopprimiOdonimoInput, "data_soppressione", "2024-10-08"),
        (SopprimiOdonimoInput, "data_soppressione", "31/02/2025"),
        # metodo: survey method 1-4
        (AggiornaCoordinateInput, "metodo", "5"),
        (AggiornaCoordinateInput, "metodo", "0"),
        (AggiornaCoordinateDaProgressivoAccessoInput, "metodo", "33"),
    ],
)
def test_invalid_value_is_rejected_with_the_field_named(model, field, bad_value):
    with pytest.raises(ValidationError) as excinfo:
        model(**{**VALID[model], field: bad_value})
    assert any(field in error["loc"] for error in excinfo.value.errors())
