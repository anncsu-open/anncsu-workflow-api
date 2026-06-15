"""Input constraints mirroring the ANNCSU OAS / anncsu-sdk validation rules.

The SDK validates payloads only in its CLI layer, so nothing checks them on the
service path before the server answers with opaque errors (e.g. error 100).
The facade input models therefore enforce the documented constraints up front:
Belfiore codcom format, OAS max lengths, DD/MM/YYYY calendar dates, metodo 1-4.
"""

import pytest
from pydantic import ValidationError

from app.models.workflows import (
    AggiornaAccessoDaProgressivoInput,
    AggiornaOdonimoDaProgressivoInput,
    CreaIndirizzoCompletoInput,
    RicercaIndirizzoInput,
    SopprimiAccessoInput,
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
    AggiornaAccessoDaProgressivoInput: {
        "codcom": "H501",
        "prognaz": "2000449",
        "prognazacc": "1370588",
        "numero": "42",
        "sezione_censimento": "580911010001",
    },
    SopprimiAccessoInput: {
        "codcom": "H501",
        "prognaz": "2000449",
        "prognazacc": "1370588",
        "data_soppressione": "08/10/2024",
    },
    AggiornaOdonimoDaProgressivoInput: {
        "codcom": "H501",
        "prognaz": "2000449",
        "denom_delibera": "VIA ROMA",
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
        (SopprimiOdonimoInput, "codcom", "501H"),
        (RicercaIndirizzoInput, "codcom", "h501"),
        # OAS max lengths (AccessoMaxLengthError in the SDK)
        (CreaIndirizzoCompletoInput, "numero_civico", "123456"),  # max 5
        (CreaIndirizzoCompletoInput, "sezione_censimento", "1" * 14),  # max 13
        (CreaIndirizzoCompletoInput, "denom_odonimo", "X" * 121),  # max 120
        (RicercaIndirizzoInput, "numero_civico", "123456"),
        # dates: valid DD/MM/YYYY calendar dates (InvalidDateFormatError in the SDK)
        (CreaIndirizzoCompletoInput, "data_validita", "2024-10-08"),
        (CreaIndirizzoCompletoInput, "data_validita", "31/02/2025"),
        (CreaIndirizzoCompletoInput, "data_validita", "01/01/2099"),  # not in future (odonimo rule)
        (SopprimiOdonimoInput, "data_soppressione", "2024-10-08"),
        (SopprimiOdonimoInput, "data_soppressione", "31/02/2025"),
        (SopprimiAccessoInput, "codcom", "h501"),
        (SopprimiAccessoInput, "prognaz", "1" * 11),  # max 10
        (SopprimiAccessoInput, "prognazacc", "1" * 16),  # max 15
        (SopprimiAccessoInput, "data_soppressione", "31/02/2025"),
        # odonimo update (ADR 0013)
        (AggiornaOdonimoDaProgressivoInput, "codcom", "h501"),
        (AggiornaOdonimoDaProgressivoInput, "prognaz", "1" * 11),  # max 10
        (AggiornaOdonimoDaProgressivoInput, "denom_delibera", "X" * 121),  # max 120
        (AggiornaOdonimoDaProgressivoInput, "dug", "X" * 31),  # max 30
        (AggiornaOdonimoDaProgressivoInput, "denom_localita", "X" * 152),  # max 151
        (AggiornaOdonimoDaProgressivoInput, "denom_in_lingua_1", "X" * 151),  # max 150
        (AggiornaOdonimoDaProgressivoInput, "denom_in_lingua_2", "X" * 151),  # max 150
        (AggiornaOdonimoDaProgressivoInput, "codice_comunale", "X" * 31),  # max 30
        (AggiornaOdonimoDaProgressivoInput, "data_validita", "31/02/2025"),
        (AggiornaOdonimoDaProgressivoInput, "data_validita", "01/01/2099"),  # not in future
        # generic accesso update (ADR 0010 / 0012)
        (AggiornaAccessoDaProgressivoInput, "metodo", "5"),  # survey method 1-4
        (AggiornaAccessoDaProgressivoInput, "codcom", "h501"),
        (AggiornaAccessoDaProgressivoInput, "prognaz", "1" * 11),  # max 10
        (AggiornaAccessoDaProgressivoInput, "prognazacc", "1" * 16),  # max 15
        (AggiornaAccessoDaProgressivoInput, "numero", "123456"),  # max 5
        (AggiornaAccessoDaProgressivoInput, "esponente", "X" * 16),  # max 15
        (AggiornaAccessoDaProgressivoInput, "specificita", "X" * 6),  # max 5
        (AggiornaAccessoDaProgressivoInput, "isolato", "12345"),  # max 4
        (AggiornaAccessoDaProgressivoInput, "codice_civico_comunale", "X" * 31),  # max 30
        (AggiornaAccessoDaProgressivoInput, "sezione_censimento", "1" * 14),  # max 13
        (AggiornaAccessoDaProgressivoInput, "data_validita", "31/02/2025"),
    ],
)
def test_invalid_value_is_rejected_with_the_field_named(model, field, bad_value):
    with pytest.raises(ValidationError) as excinfo:
        model(**{**VALID[model], field: bad_value})
    assert any(field in error["loc"] for error in excinfo.value.errors())


def test_accesso_update_rejects_both_numero_and_metrico():
    """Civic XOR metric: providing both is rejected (patch may omit both)."""
    with pytest.raises(ValidationError) as excinfo:
        AggiornaAccessoDaProgressivoInput(
            **{**VALID[AggiornaAccessoDaProgressivoInput], "metrico": "300"}
        )
    assert "numero" in str(excinfo.value) and "metrico" in str(excinfo.value)


def test_accesso_update_allows_neither_numero_nor_metrico():
    """Patch (ADR 0012): both may be omitted and preserved from the read."""
    payload = {**VALID[AggiornaAccessoDaProgressivoInput]}
    payload.pop("numero")
    assert AggiornaAccessoDaProgressivoInput(**payload)


def test_accesso_update_accepts_explicit_none_on_every_nullable_field():
    assert AggiornaAccessoDaProgressivoInput(
        **VALID[AggiornaAccessoDaProgressivoInput],
        metrico=None,
        esponente=None,
        specificita=None,
        isolato=None,
        codice_civico_comunale=None,
        data_validita=None,
    )


def test_accesso_update_accepts_a_metric_accesso():
    payload = {**VALID[AggiornaAccessoDaProgressivoInput]}
    payload.pop("numero")
    assert AggiornaAccessoDaProgressivoInput(**payload, metrico="300")


# --- embedded coordinates: conditional presence (OAS co-dependency rules) ---

_BASE = VALID[AggiornaAccessoDaProgressivoInput]


def test_accesso_update_accepts_complete_absence_of_coordinates():
    """Coordinates are optional: an attribute-only update needs none of x/y/z/metodo."""
    model = AggiornaAccessoDaProgressivoInput(**_BASE)
    assert model.coordinata_x is None
    assert model.coordinata_y is None
    assert model.coordinata_z is None
    assert model.metodo is None


@pytest.mark.parametrize(
    "coords",
    [
        {"coordinata_x": "13.1022000", "coordinata_y": "41.8847600"},  # x + y
        {"coordinata_x": "13.1022000", "coordinata_y": "41.8847600", "metodo": "3"},
        {
            "coordinata_x": "13.1022000",
            "coordinata_y": "41.8847600",
            "coordinata_z": "150",
            "metodo": "3",
        },
    ],
)
def test_accesso_update_accepts_well_formed_coordinate_sets(coords):
    assert AggiornaAccessoDaProgressivoInput(**_BASE, **coords)


@pytest.mark.parametrize(
    "coords",
    [
        {"coordinata_x": "13.1022000"},  # x without y
        {"coordinata_y": "41.8847600"},  # y without x
        {"coordinata_z": "150"},  # z (quota) without x/y
        {"metodo": "3"},  # metodo without x/y
        {"coordinata_z": "150", "metodo": "3"},  # z + metodo, still no x/y
    ],
)
def test_accesso_update_rejects_partial_coordinate_sets(coords):
    """x and y are co-required; z and metodo are only allowed alongside x and y."""
    with pytest.raises(ValidationError):
        AggiornaAccessoDaProgressivoInput(**_BASE, **coords)


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        ("coordinata_x", "not-a-number"),
        ("coordinata_x", "5.9"),  # below the Italy longitude bound
        ("coordinata_y", "35.9"),  # below the Italy latitude bound
    ],
)
def test_accesso_update_rejects_invalid_coordinate_values(field, bad_value):
    coords = {"coordinata_x": "13.1022000", "coordinata_y": "41.8847600", field: bad_value}
    with pytest.raises(ValidationError) as excinfo:
        AggiornaAccessoDaProgressivoInput(**_BASE, **coords)
    assert any(field in error["loc"] for error in excinfo.value.errors())


# --- odonimo update: administrative-object co-dependencies (ADR 0013) ---

_ODONIMO_BASE = VALID[AggiornaOdonimoDaProgressivoInput]


def _odonimo(**extra) -> AggiornaOdonimoDaProgressivoInput:
    # model_validate mirrors the JSON -> dict -> model path the route uses, so the
    # nested administrative objects (provvedimento/aut_prefettura) are coerced as dicts.
    return AggiornaOdonimoDaProgressivoInput.model_validate({**_ODONIMO_BASE, **extra})


def test_odonimo_update_accepts_minimal_input():
    assert _odonimo()


@pytest.mark.parametrize("flag", ["5", "9", "x"])
def test_odonimo_rejects_invalid_flag_delibera(flag):
    with pytest.raises(ValidationError):
        _odonimo(provvedimento={"flag_delibera": flag, "data": "01/01/2024", "protocollo": "P1"})


@pytest.mark.parametrize("flag", ["0", "1"])
def test_odonimo_flag_delibera_0_1_requires_data_and_protocollo(flag):
    with pytest.raises(ValidationError):
        _odonimo(provvedimento={"flag_delibera": flag})


def test_odonimo_flag_delibera_0_1_accepts_data_and_protocollo():
    assert _odonimo(provvedimento={"flag_delibera": "1", "data": "01/01/2024", "protocollo": "P1"})


def test_odonimo_flag_delibera_2_does_not_require_data_protocollo():
    assert _odonimo(provvedimento={"flag_delibera": "2"})


@pytest.mark.parametrize(
    "pref",
    [
        {"data_pref": "01/01/2024"},  # protocollo_pref missing
        {"protocollo_pref": "PREF1"},  # data_pref missing
    ],
)
def test_odonimo_prefettura_fields_are_co_required(pref):
    with pytest.raises(ValidationError):
        _odonimo(aut_prefettura=pref)


def test_odonimo_prefettura_accepts_both_fields():
    assert _odonimo(aut_prefettura={"data_pref": "01/01/2024", "protocollo_pref": "PREF1"})


@pytest.mark.parametrize(
    "provvedimento",
    [
        {"flag_delibera": "0", "data": "01/01/2024"},  # protocollo missing
        {"flag_delibera": "1", "protocollo": "P1"},  # data missing
    ],
)
def test_odonimo_flag_delibera_0_1_rejects_partial_details(provvedimento):
    """flag 0/1 requires BOTH data and protocollo — one alone is not enough."""
    with pytest.raises(ValidationError):
        _odonimo(provvedimento=provvedimento)


@pytest.mark.parametrize(
    "nested",
    [
        {"provvedimento": {"flag_delibera": "1", "data": "31/02/2024", "protocollo": "P1"}},
        {"aut_prefettura": {"data_pref": "2024-01-01", "protocollo_pref": "P1"}},
    ],
)
def test_odonimo_nested_dates_must_be_ddmmyyyy(nested):
    with pytest.raises(ValidationError):
        _odonimo(**nested)


# ============================================================================
# Complete-address creation: full accesso/odonimo fields + metric (ADR 0016)
# ============================================================================


def _crea(**extra) -> CreaIndirizzoCompletoInput:
    base = {
        "codcom": "H501",
        "denom_odonimo": "ROMA",
        "dug": "VIA",
        "numero_civico": "42",
        "sezione_censimento": "580911010001",
    }
    # model_validate mirrors the JSON -> dict -> model path the route uses, so the
    # nested objects (provvedimento/aut_prefettura) are coerced from dicts.
    return CreaIndirizzoCompletoInput.model_validate({**base, **extra})


def test_crea_requires_an_accesso_identifier():
    with pytest.raises(ValidationError):
        _crea(numero_civico=None)  # neither numero nor metrico


def test_crea_rejects_both_numero_and_metrico():
    with pytest.raises(ValidationError):
        _crea(metrico="300")  # numero_civico is "42" from the base


def test_crea_accepts_a_metric_accesso():
    model = _crea(numero_civico=None, metrico="300")
    assert model.metrico == "300"
    assert model.numero_civico is None


def test_crea_defaults_the_delibera_for_backward_compatibility():
    model = _crea()  # no denom_delibera / provvedimento provided
    assert model.denom_delibera == "ROMA"  # falls back to denom_odonimo
    assert model.provvedimento is not None
    assert model.provvedimento.flag_delibera == "2"


def test_crea_accepts_the_full_accesso_and_odonimo_fields():
    model = _crea(
        esponente="A",
        specificita="ROSSO",
        isolato="12",
        codice_civico_comunale="7569A",
        coordinata_x="13.1022000",
        coordinata_y="41.8847600",
        coordinata_z="150",
        metodo="3",
        denom_localita="CENTRO",
        denom_in_lingua_1="X",
        denom_in_lingua_2="Y",
        codice_comunale="C1",
        denom_delibera="VIA ROMA",
        provvedimento={"flag_delibera": "2"},
        aut_prefettura={"data_pref": "01/01/2024", "protocollo_pref": "PREF1"},
    )
    assert model.esponente == "A"
    assert model.coordinata_x == "13.1022000"
    assert model.denom_localita == "CENTRO"
    assert model.denom_delibera == "VIA ROMA"
    assert model.aut_prefettura is not None
    assert model.aut_prefettura.protocollo_pref == "PREF1"


@pytest.mark.parametrize(
    "coords",
    [
        {"coordinata_x": "13.1022000"},  # x without y
        {"coordinata_y": "41.8847600"},  # y without x
        {"coordinata_z": "150"},  # z without x/y
        {"metodo": "3"},  # metodo without x/y
    ],
)
def test_crea_rejects_partial_coordinate_sets(coords):
    with pytest.raises(ValidationError):
        _crea(**coords)


@pytest.mark.parametrize(
    ("field", "bad"),
    [
        ("coordinata_x", "5.0"),  # below 6.0 (Italy bounds)
        ("coordinata_y", "50.0"),  # above 47.0
    ],
)
def test_crea_rejects_out_of_bounds_coordinates(field, bad):
    partner = (
        {"coordinata_y": "41.8847600"}
        if field == "coordinata_x"
        else {"coordinata_x": "13.1022000"}
    )
    with pytest.raises(ValidationError):
        _crea(**partner, **{field: bad})
