"""Tests for Pydantic models using Polyfactory and Faker."""

import pytest
from pydantic import ValidationError

from app.models.workflows import (
    AccessoResult,
    AggiornaAccessoDaProgressivoInput,
    CreaIndirizzoCompletoInput,
    CreaIndirizzoCompletoOutput,
    OdonimoResult,
    SopprimiOdonimoInput,
)
from tests.factories import (
    AccessoResultFactory,
    CreaIndirizzoCompletoInputFactory,
    CreaIndirizzoCompletoOutputFactory,
    OdonimoResultFactory,
    RicercaIndirizzoInputFactory,
    RicercaIndirizzoOutputFactory,
    SopprimiOdonimoInputFactory,
    SopprimiOdonimoOutputFactory,
)

# ============================================================================
# Test CreaIndirizzoCompletoInput
# ============================================================================


class TestCreaIndirizzoCompletoInput:
    """Test suite for CreaIndirizzoCompletoInput model."""

    def test_factory_generates_valid_model(self):
        """Test that the factory generates a valid model."""
        model = CreaIndirizzoCompletoInputFactory.build()
        assert isinstance(model, CreaIndirizzoCompletoInput)
        assert model.codcom is not None
        assert model.denom_odonimo is not None
        assert model.dug is not None
        assert model.numero_civico is not None

    def test_factory_batch_generation(self):
        """Test batch generation of models."""
        models = CreaIndirizzoCompletoInputFactory.batch(10)
        assert len(models) == 10
        assert all(isinstance(m, CreaIndirizzoCompletoInput) for m in models)
        # Verify that the data is different
        codcoms = [m.codcom for m in models]
        assert len(set(codcoms)) > 1  # At least some codes must be different

    def test_factory_with_overrides(self):
        """Test factory with overrides of specific fields."""
        model = CreaIndirizzoCompletoInputFactory.build(
            codcom="H501",
            denom_odonimo="ROMA",
            numero_civico="42",
        )
        assert model.codcom == "H501"
        assert model.denom_odonimo == "ROMA"
        assert model.numero_civico == "42"

    def test_missing_required_fields(self):
        """Test validation with missing required fields."""
        with pytest.raises(ValidationError) as exc_info:
            CreaIndirizzoCompletoInput(
                codcom="H501",
                denom_odonimo="ROMA",
                numero_civico="42",  # an accesso identifier (keeps the XOR satisfied)
                # dug and sezione_censimento missing
            )
        # Type-safe access to ValidationError.errors()
        validation_error = exc_info.value
        assert isinstance(validation_error, ValidationError)
        errors = validation_error.errors()
        error_fields = {e["loc"][0] for e in errors if e["loc"]}
        assert "dug" in error_fields
        assert "sezione_censimento" in error_fields

    def test_optional_fields_can_be_none(self):
        """Test that optional fields can be None."""
        model = CreaIndirizzoCompletoInputFactory.build(
            data_validita=None,
        )
        assert model.data_validita is None

    def test_model_serialization(self):
        """Test model serialization."""
        model = CreaIndirizzoCompletoInputFactory.build()
        data = model.model_dump()
        assert isinstance(data, dict)
        assert "codcom" in data
        assert "denom_odonimo" in data

    def test_model_json_schema(self):
        """Test that the model has a valid JSON schema."""
        schema = CreaIndirizzoCompletoInput.model_json_schema()
        assert "properties" in schema
        assert "required" in schema
        assert "codcom" in schema["required"]


# ============================================================================
# Test CreaIndirizzoCompletoOutput
# ============================================================================


class TestCreaIndirizzoCompletoOutput:
    """Test suite for CreaIndirizzoCompletoOutput model."""

    def test_factory_generates_valid_model(self):
        """Test that the factory generates a valid model."""
        model = CreaIndirizzoCompletoOutputFactory.build()
        assert isinstance(model, CreaIndirizzoCompletoOutput)
        assert isinstance(model.success, bool)
        assert model.message is not None

    def test_success_output(self):
        """Test success output."""
        model = CreaIndirizzoCompletoOutputFactory.build(
            success=True,
            progressivo_nazionale_odonimo="2000449",
            progressivo_civico="1370588",
            errors=None,
        )
        assert model.success is True
        assert model.progressivo_nazionale_odonimo == "2000449"
        assert model.progressivo_civico == "1370588"
        assert model.errors is None

    def test_failure_output_with_errors(self):
        """Test error output with a list of errors."""
        model = CreaIndirizzoCompletoOutputFactory.build(
            success=False,
            errors=["Errore 1", "Errore 2"],
        )
        assert model.success is False
        assert model.errors is not None
        assert len(model.errors) == 2

    def test_batch_generation_success_rate(self):
        """Test that most generated models have success=True."""
        models = CreaIndirizzoCompletoOutputFactory.batch(100)
        success_count = sum(1 for m in models if m.success)
        # The factory is configured for ~80% successes
        assert success_count >= 70  # At least 70%


# ============================================================================
# Test SopprimiOdonimoInput
# ============================================================================


class TestSopprimiOdonimoInput:
    """Test suite for SopprimiOdonimoInput model."""

    def test_factory_generates_valid_date(self):
        """Test that the factory generates dates in the correct format."""
        models = SopprimiOdonimoInputFactory.batch(20)
        for model in models:
            # Verify DD/MM/YYYY format
            parts = model.data_soppressione.split("/")
            assert len(parts) == 3
            assert len(parts[0]) == 2  # day
            assert len(parts[1]) == 2  # month
            assert len(parts[2]) == 4  # year

    def test_all_fields_required(self):
        """Test that all fields are required."""
        with pytest.raises(ValidationError):
            SopprimiOdonimoInput(
                codcom="H501",
                # denom_odonimo missing
                # data_soppressione missing
            )


# ============================================================================
# Test SopprimiOdonimoOutput
# ============================================================================


class TestSopprimiOdonimoOutput:
    """Test suite for SopprimiOdonimoOutput model."""

    def test_factory_generates_accessi_list(self):
        """Test that the factory generates a list of associated accessi."""
        models = SopprimiOdonimoOutputFactory.batch(30)
        models_with_accessi = [m for m in models if m.accessi_presenti is not None]

        for model in models_with_accessi:
            assert isinstance(model.accessi_presenti, list)
            assert all(isinstance(a, AccessoResult) for a in model.accessi_presenti)


# ============================================================================
# Test RicercaIndirizzoInput
# ============================================================================


class TestRicercaIndirizzoInput:
    """Test suite for RicercaIndirizzoInput model."""

    def test_factory_generates_with_optional_civico(self):
        """Test that numero_civico is optional."""
        models = RicercaIndirizzoInputFactory.batch(20)
        with_civico = [m for m in models if m.numero_civico is not None]
        without_civico = [m for m in models if m.numero_civico is None]

        # We should have roughly 50% with and without
        assert len(with_civico) > 0
        assert len(without_civico) > 0

    def test_search_only_by_odonimo(self):
        """Test search by odonimo only."""
        model = RicercaIndirizzoInputFactory.build(numero_civico=None)
        assert model.codcom is not None
        assert model.denom_odonimo is not None
        assert model.numero_civico is None


# ============================================================================
# Test OdonimoResult
# ============================================================================


class TestOdonimoResult:
    """Test suite for OdonimoResult model."""

    def test_factory_generates_valid_odonimo(self):
        """Test that the factory generates valid odonimi."""
        models = OdonimoResultFactory.batch(30)
        for model in models:
            assert model.prognaz is not None
            assert model.dug is not None
            assert model.duf is not None

    def test_optional_language_fields(self):
        """Test that the language fields are optional."""
        model = OdonimoResultFactory.build(
            denomlingua1=None,
            denomlingua2=None,
        )
        assert model.denomlingua1 is None
        assert model.denomlingua2 is None


# ============================================================================
# Test AccessoResult
# ============================================================================


class TestAccessoResult:
    """Test suite for AccessoResult model."""

    def test_factory_generates_valid_accesso(self):
        """Test that the factory generates valid accessi."""
        models = AccessoResultFactory.batch(30)
        for model in models:
            assert model.prognazacc is not None
            # civico should be present in most cases
            if model.civico:
                assert int(model.civico) > 0

    def test_accesso_with_coordinates(self):
        """Test accesso with coordinates."""
        model = AccessoResultFactory.build(
            coordX="13.1022000",
            coordY="41.8847600",
            quota="150",
            metodo="3",
        )
        assert model.coordX is not None
        assert model.coordY is not None
        x = float(model.coordX)
        y = float(model.coordY)
        assert 6.0 <= x <= 18.0
        assert 36.0 <= y <= 47.0


# ============================================================================
# Test RicercaIndirizzoOutput
# ============================================================================


class TestRicercaIndirizzoOutput:
    """Test suite for RicercaIndirizzoOutput model."""

    def test_factory_generates_results_lists(self):
        """Test that the factory generates lists of results."""
        models = RicercaIndirizzoOutputFactory.batch(20)
        for model in models:
            assert isinstance(model.odonimi, list)
            assert isinstance(model.accessi, list)
            # Verify that the elements in the lists are of the correct type
            for odonimo in model.odonimi:
                assert isinstance(odonimo, OdonimoResult)
            for accesso in model.accessi:
                assert isinstance(accesso, AccessoResult)

    def test_empty_results(self):
        """Test empty results."""
        model = RicercaIndirizzoOutputFactory.build(
            success=True,
            odonimi=[],
            accessi=[],
            errors=None,
        )
        assert model.success is True
        assert len(model.odonimi) == 0
        assert len(model.accessi) == 0

    def test_results_with_multiple_odonimi(self):
        """Test with multiple odonimi."""
        odonimi = OdonimoResultFactory.batch(5)
        accessi = AccessoResultFactory.batch(10)
        model = RicercaIndirizzoOutputFactory.build(
            success=True,
            odonimi=odonimi,
            accessi=accessi,
        )
        assert len(model.odonimi) == 5
        assert len(model.accessi) == 10

    def test_serialization_with_nested_models(self):
        """Test serialization with nested models."""
        model = RicercaIndirizzoOutputFactory.build()
        data = model.model_dump()
        assert isinstance(data, dict)
        assert "odonimi" in data
        assert "accessi" in data
        assert isinstance(data["odonimi"], list)
        assert isinstance(data["accessi"], list)


# ============================================================================
# Integration tests with real-world scenarios
# ============================================================================


class TestRealWorldScenarios:
    """Tests with realistic scenarios."""

    def test_complete_address_creation_workflow(self):
        """Test the complete address creation workflow."""
        # Input
        input_data = CreaIndirizzoCompletoInputFactory.build(
            codcom="H501",
            denom_odonimo="GARIBALDI",
            dug="VIA",
            numero_civico="42",
            data_validita="08/10/2024",
        )

        # Success output
        output_data = CreaIndirizzoCompletoOutputFactory.build(
            success=True,
            progressivo_nazionale_odonimo="2000449",
            progressivo_civico="1370588",
            message="Indirizzo creato con successo",
            errors=None,
        )

        assert input_data.codcom == "H501"
        assert output_data.success is True
        assert output_data.progressivo_civico == "1370588"

    def test_search_returns_multiple_results(self):
        """Test a search that returns multiple results."""
        # Simulate a partial search by odonimo
        # search_input would be used to call the consultazione API

        # Simulate multiple results
        odonimi = [
            OdonimoResultFactory.build(dug="VIA", duf="ROMA"),
            OdonimoResultFactory.build(dug="PIAZZA", duf="ROMA"),
            OdonimoResultFactory.build(dug="CORSO", duf="ROMANO"),
        ]

        search_output = RicercaIndirizzoOutputFactory.build(
            success=True,
            odonimi=odonimi,
            accessi=[],
            message=f"Trovati {len(odonimi)} odonimi",
        )

        assert len(search_output.odonimi) == 3
        assert all("ROM" in (o.duf or "") for o in search_output.odonimi)

    def test_coordinate_update_with_gps(self):
        """Realistic GPS coordinates pass the WGS84 validators on the accesso update."""
        # Roma Colosseo (real coordinates)
        input_data = AggiornaAccessoDaProgressivoInput(
            codcom="H501",
            prognaz="2000449",
            prognazacc="1370588",
            sezione_censimento="580911010001",
            coordinata_x="12.4922309",  # Colosseo longitude
            coordinata_y="41.8902142",  # Colosseo latitude
            coordinata_z="20",
            metodo="4",  # GPS
        )

        assert input_data.coordinata_x is not None
        assert input_data.coordinata_y is not None
        assert float(input_data.coordinata_x) == pytest.approx(12.4922309)
        assert float(input_data.coordinata_y) == pytest.approx(41.8902142)
        assert input_data.metodo == "4"
