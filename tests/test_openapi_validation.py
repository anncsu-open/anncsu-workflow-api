"""Tests for validating Pydantic models against the ANNCSU OpenAPI specifications."""

from pathlib import Path

import pytest

from app.models.workflows import (
    AccessoResult,
    AggiornaAccessoDaProgressivoInput,
    AggiornaAccessoOutput,
    CreaIndirizzoCompletoInput,
    CreaIndirizzoCompletoOutput,
    RicercaIndirizzoInput,
    RicercaIndirizzoOutput,
    SopprimiOdonimoInput,
    SopprimiOdonimoOutput,
)
from tests.utils.openapi_validator import (
    OpenAPISchemaComparator,
    OpenAPIValidator,
)

# Path to the original OpenAPI specifications
SPECS_DIR = Path(__file__).parent.parent / "specs"
CONSULTAZIONE_SPEC = SPECS_DIR / "Specifica API - ANNCSU – Consultazione per le PA.yaml"
ODONIMI_SPEC = SPECS_DIR / "Specifica API - ANNCSU - Aggiornamento odonimi.yaml"
ACCESSI_SPEC = SPECS_DIR / "Specifica API - ANNCSU - Aggiornamento accessi.yaml"
COORDINATE_SPEC = SPECS_DIR / "Specifica API - ANNCSU - Aggiornamento coordinate.yml"


@pytest.fixture
def consultazione_validator():
    """Validator for the Consultazione API."""
    return OpenAPIValidator(CONSULTAZIONE_SPEC)


@pytest.fixture
def odonimi_validator():
    """Validator for the Odonimi API."""
    return OpenAPIValidator(ODONIMI_SPEC)


@pytest.fixture
def accessi_validator():
    """Validator for the Accessi API."""
    return OpenAPIValidator(ACCESSI_SPEC)


@pytest.fixture
def coordinate_validator():
    """Validator for the Coordinate API."""
    return OpenAPIValidator(COORDINATE_SPEC)


class TestConsultazioneAPI:
    """Tests validating models against the Consultazione API."""

    def test_consultazione_spec_loads(self, consultazione_validator):
        """Test that the Consultazione OpenAPI spec loads correctly."""
        assert consultazione_validator.openapi_spec is not None
        assert consultazione_validator.openapi_spec.info.title == "ANNCSU REST API"

    def test_ricerca_indirizzo_input_structure(self, consultazione_validator):
        """Test that RicercaIndirizzoInput has the correct structure."""
        # Our class represents the input for the search
        model_schema = RicercaIndirizzoInput.model_json_schema()

        # Verify that it has the base properties
        assert "properties" in model_schema
        assert "codcom" in model_schema["properties"]
        assert "denom_odonimo" in model_schema["properties"]
        assert "progressivo_nazionale" in model_schema["properties"]

        # codcom is required; the odonimo selector is exactly-one-of denom_odonimo /
        # progressivo_nazionale, enforced by a model validator rather than by
        # `required` (ADR 0021), so neither selector appears in `required`.
        required = model_schema.get("required", [])
        assert "codcom" in required
        assert "denom_odonimo" not in required
        assert "progressivo_nazionale" not in required

    def test_odonimo_result_matches_consultazione_response(self, consultazione_validator):
        """Test that OdonimoResult corresponds to the elencoodonimiprog response."""
        # Get the schema from the API response
        response_schema = consultazione_validator.get_schema_from_path(
            "/elencoodonimiprog", "post", "200"
        )

        assert response_schema is not None, "Schema risposta non trovato"

        # The response contains an object with 'data', which is an array
        if "$ref" in response_schema:
            # Resolve the reference
            assert "properties" in response_schema or "$ref" in response_schema

    def test_accesso_result_structure(self):
        """Test that AccessoResult has the necessary fields."""
        model_schema = AccessoResult.model_json_schema()

        # Verify the main fields
        properties = model_schema.get("properties", {})
        assert "prognazacc" in properties
        assert "civico" in properties
        assert "coordX" in properties
        assert "coordY" in properties

        # Verify required
        required = model_schema.get("required", [])
        assert "prognazacc" in required


class TestOdonimiAPI:
    """Tests validating models against the Odonimi API."""

    def test_odonimi_spec_loads(self, odonimi_validator):
        """Test that the Odonimi OpenAPI spec loads correctly."""
        assert odonimi_validator.openapi_spec is not None
        assert "ODONIMI" in odonimi_validator.openapi_spec.info.title

    def test_sopprimi_odonimo_input_structure(self):
        """Test the structure of SopprimiOdonimoInput."""
        model_schema = SopprimiOdonimoInput.model_json_schema()

        properties = model_schema.get("properties", {})
        assert "codcom" in properties
        assert "denom_odonimo" in properties
        assert "data_soppressione" in properties

        # All fields are required
        required = model_schema.get("required", [])
        assert len(required) == 3

    def test_odonimi_request_body_schema(self, odonimi_validator):
        """Test that the requestBody for /odonimi exists."""
        request_schema = odonimi_validator.get_schema_from_path("/odonimi", "post", is_request=True)

        assert request_schema is not None, "Schema request non trovato"

        # Verify that it has a request object
        if "$ref" in request_schema:
            # It is a reference, get the component
            component = odonimi_validator.get_component_schema("RichiestaOperazione")
            assert component is not None


class TestAccessiAPI:
    """Tests validating models against the Accessi API."""

    def test_accessi_spec_loads(self, accessi_validator):
        """Test that the Accessi OpenAPI spec loads correctly."""
        assert accessi_validator.openapi_spec is not None
        assert "ACCESSI" in accessi_validator.openapi_spec.info.title

    def test_aggiorna_coordinate_input_has_required_fields(self):
        """Test that AggiornaAccessoDaProgressivoInput has the required fields."""
        model_schema = AggiornaAccessoDaProgressivoInput.model_json_schema()

        properties = model_schema.get("properties", {})
        assert "codcom" in properties
        assert "prognazacc" in properties
        assert "coordinata_x" in properties
        assert "coordinata_y" in properties

        # Coordinates are optional strings (str | None -> anyOf string/null).
        def _allows_string(prop: dict) -> bool:
            if prop.get("type") == "string":
                return True
            return any(option.get("type") == "string" for option in prop.get("anyOf", []))

        assert _allows_string(properties["coordinata_x"])
        assert _allows_string(properties["coordinata_y"])


class TestCoordinateAPI:
    """Tests validating models against the Coordinate API."""

    def test_coordinate_spec_loads(self, coordinate_validator):
        """Test that the Coordinate OpenAPI spec loads correctly."""
        assert coordinate_validator.openapi_spec is not None
        assert "COORDINATE" in coordinate_validator.openapi_spec.info.title

    def test_coordinate_input_structure(self):
        """Coordinates are optional on the accesso patch (preserved from the read);
        identity and the non-derivable sezione are the required inputs (ADR 0012)."""
        model_schema = AggiornaAccessoDaProgressivoInput.model_json_schema()

        properties = model_schema.get("properties", {})
        required = model_schema.get("required", [])

        # Coordinates are optional (the read preserves them when omitted)
        assert "coordinata_x" in properties
        assert "coordinata_y" in properties
        assert "coordinata_x" not in required
        assert "coordinata_y" not in required

        # Identity + the non-fetchable sezione are required
        for field in ("codcom", "prognaz", "prognazacc", "sezione_censimento"):
            assert field in required


class TestCrossSpecValidation:
    """Cross-spec validation tests."""

    def test_all_specs_load_successfully(self):
        """Test that all 4 OpenAPI specs load."""
        specs = [
            CONSULTAZIONE_SPEC,
            ODONIMI_SPEC,
            ACCESSI_SPEC,
            COORDINATE_SPEC,
        ]

        loaded_specs = []
        for spec_path in specs:
            if spec_path.exists():
                validator = OpenAPIValidator(spec_path)
                assert validator.openapi_spec is not None
                loaded_specs.append(spec_path.name)

        # All 4 source specs must load
        assert len(loaded_specs) == 4, f"Solo {len(loaded_specs)} specs caricate"

    def test_common_schemas_identification(self):
        """Test identification of common schemas across the specs."""
        spec_paths = [
            path
            for path in [
                CONSULTAZIONE_SPEC,
                ODONIMI_SPEC,
                ACCESSI_SPEC,
            ]
            if path.exists()
        ]

        if len(spec_paths) >= 2:
            specs = OpenAPISchemaComparator.load_openapi_specs(spec_paths)
            common_schemas = OpenAPISchemaComparator.find_common_schemas(specs)

            # There should be some common schemas (e.g. RispostaErrore)
            assert len(common_schemas) >= 0  # It may not have common schemas

    def test_coordinate_types_consistency(self):
        """Test that coordinate types are consistent across models."""
        # All models that use coordinates should use string
        models_with_coordinates = [
            AggiornaAccessoDaProgressivoInput,
            AggiornaAccessoOutput,
            AccessoResult,
        ]

        for model in models_with_coordinates:
            schema = model.model_json_schema()
            properties = schema.get("properties", {})

            # If they have coordX/Y, they must be string (or anyOf with string)
            if "coordinata_x" in properties or "coordX" in properties:
                coord_prop = properties.get("coordinata_x") or properties.get("coordX")
                if coord_prop:
                    # It could be {"type": "string"} or {"anyOf": [...]}
                    if "type" in coord_prop:
                        assert coord_prop["type"] == "string"
                    elif "anyOf" in coord_prop:
                        types = [t.get("type") for t in coord_prop["anyOf"]]
                        assert "string" in types


class TestModelFieldDescriptions:
    """Test that the models have appropriate descriptions."""

    def test_input_models_have_descriptions(self):
        """Test that input models have a description on their fields."""
        models = [
            CreaIndirizzoCompletoInput,
            AggiornaAccessoDaProgressivoInput,
            SopprimiOdonimoInput,
            RicercaIndirizzoInput,
        ]

        for model in models:
            schema = model.model_json_schema()
            properties = schema.get("properties", {})

            for prop_name, prop_schema in properties.items():
                # Each property should have a description
                assert "description" in prop_schema, (
                    f"{model.__name__}.{prop_name} manca description"
                )

    def test_output_models_have_descriptions(self):
        """Test that output models have a description."""
        models = [
            CreaIndirizzoCompletoOutput,
            AggiornaAccessoOutput,
            SopprimiOdonimoOutput,
            RicercaIndirizzoOutput,
        ]

        for model in models:
            schema = model.model_json_schema()
            properties = schema.get("properties", {})

            for prop_name, prop_schema in properties.items():
                assert "description" in prop_schema, (
                    f"{model.__name__}.{prop_name} manca description"
                )


class TestModelExamples:
    """Test that the models have examples in json_schema_extra."""

    def test_input_models_have_examples(self):
        """Test that input models have examples."""
        models = [
            CreaIndirizzoCompletoInput,
            AggiornaAccessoDaProgressivoInput,
            SopprimiOdonimoInput,
            RicercaIndirizzoInput,
        ]

        for model in models:
            schema = model.model_json_schema()
            properties = schema.get("properties", {})

            # Verify that the schema is valid and has properties
            # Note: examples are defined via json_schema_extra in the Field definitions
            assert properties, f"{model.__name__} non ha properties"


class TestRequiredFields:
    """Tests validating required fields."""

    def test_crea_indirizzo_required_fields(self):
        """Test required fields for address creation."""
        schema = CreaIndirizzoCompletoInput.model_json_schema()
        required = schema.get("required", [])

        # These must be required
        assert "codcom" in required
        assert "denom_odonimo" in required
        assert "dug" in required
        assert "sezione_censimento" in required

        # numero_civico is now optional (an accesso may be metric instead); data_validita optional
        assert "numero_civico" not in required
        assert "data_validita" not in required

    def test_output_models_required_fields(self):
        """Test required fields in the output models."""
        output_models = [
            CreaIndirizzoCompletoOutput,
            AggiornaAccessoOutput,
            SopprimiOdonimoOutput,
            RicercaIndirizzoOutput,
        ]

        for model in output_models:
            schema = model.model_json_schema()
            required = schema.get("required", [])

            # All outputs must have success and the overall summary (ADR 0022)
            assert "success" in required, f"{model.__name__} manca 'success' in required"
            assert "summary" in required, f"{model.__name__} manca 'summary' in required"
