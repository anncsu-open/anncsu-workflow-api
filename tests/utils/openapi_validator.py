"""Utility for validating Pydantic models against the OpenAPI specifications."""

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import yaml

# Use OpenAPI 3.0.x instead of 3.1.x (ANNCSU uses OpenAPI 3.0.3)
from openapi_pydantic.v3.v3_0 import OpenAPI
from pydantic import BaseModel


class OpenAPIValidator:
    """Validates Pydantic models against OpenAPI schemas."""

    def __init__(self, openapi_spec_path: str | Path):
        """
        Initialize the validator with an OpenAPI spec.

        Args:
            openapi_spec_path: Path to the OpenAPI YAML file
        """
        self.spec_path = Path(openapi_spec_path)
        with open(self.spec_path, encoding="utf-8") as f:
            self.raw_spec = yaml.safe_load(f)
        self.openapi_spec = OpenAPI.model_validate(self.raw_spec)

    def get_schema_from_path(
        self,
        path: str,
        method: str,
        response_code: str = "200",
        is_request: bool = False,
    ) -> dict[str, Any] | None:
        """
        Extract a schema from an OpenAPI path.

        Args:
            path: Endpoint path (e.g. "/odonimi")
            method: HTTP method (e.g. "post")
            response_code: Response code (default "200")
            is_request: If True extract the requestBody, otherwise the response

        Returns:
            JSON schema of the component
        """
        if not self.openapi_spec.paths:
            return None

        path_item = self.openapi_spec.paths.get(path)
        if not path_item:
            return None

        operation = getattr(path_item, method.lower(), None)
        if not operation:
            return None

        if is_request:
            if not operation.requestBody:
                return None
            content = operation.requestBody.content
            if not content or "application/json" not in content:
                return None
            return content["application/json"].media_type_schema.model_dump(
                exclude_none=True, by_alias=True
            )
        else:
            if not operation.responses:
                return None
            response = operation.responses.get(response_code)
            if not response or not response.content:
                return None
            if "application/json" not in response.content:
                return None
            return response.content["application/json"].media_type_schema.model_dump(
                exclude_none=True, by_alias=True
            )

    def get_component_schema(self, component_name: str) -> dict[str, Any] | None:
        """
        Extract a schema from components/schemas.

        Args:
            component_name: Component name (e.g. "RichiestaOperazione")

        Returns:
            JSON schema of the component
        """
        if not self.openapi_spec.components or not self.openapi_spec.components.schemas:
            return None

        schema = self.openapi_spec.components.schemas.get(component_name)
        if not schema:
            return None

        return schema.model_dump(exclude_none=True, by_alias=True)

    def validate_model_against_schema(
        self, model: type[BaseModel], openapi_schema: dict[str, Any]
    ) -> tuple[bool, list[str]]:
        """
        Validate that a Pydantic model matches an OpenAPI schema.

        Args:
            model: Pydantic model class
            openapi_schema: OpenAPI schema to compare against

        Returns:
            Tuple (is_valid, errors)
        """
        errors = []

        # Get the JSON schema of the Pydantic model
        pydantic_schema = model.model_json_schema()

        # If the OpenAPI schema has a $ref, resolve it
        if "$ref" in openapi_schema:
            ref_path = openapi_schema["$ref"].split("/")
            if len(ref_path) >= 3 and ref_path[1] == "components" and ref_path[2] == "schemas":
                component_name = ref_path[3]
                resolved_schema = self.get_component_schema(component_name)
                if resolved_schema:
                    openapi_schema = resolved_schema

        # Compare the types if present
        if "type" in openapi_schema and "type" in pydantic_schema:
            if openapi_schema["type"] != pydantic_schema["type"]:
                errors.append(
                    f"Type mismatch: OpenAPI={openapi_schema['type']}, "
                    f"Pydantic={pydantic_schema['type']}"
                )

        # Compare the properties
        openapi_props = openapi_schema.get("properties", {})
        pydantic_props = pydantic_schema.get("properties", {})

        # Check that all OpenAPI properties are in the Pydantic model
        for prop_name, prop_schema in openapi_props.items():
            if prop_name not in pydantic_props:
                errors.append(f"Missing property in Pydantic model: {prop_name}")
            else:
                # Compare the property types
                openapi_type = prop_schema.get("type")
                pydantic_prop = pydantic_props[prop_name]

                # Handle anyOf/oneOf for nullable types
                if "anyOf" in pydantic_prop:
                    pydantic_types = [t.get("type") for t in pydantic_prop["anyOf"] if "type" in t]
                    if openapi_type and openapi_type not in pydantic_types:
                        if openapi_type != "null":  # Ignore differences on null
                            errors.append(
                                f"Property '{prop_name}' type mismatch: "
                                f"OpenAPI={openapi_type}, Pydantic types={pydantic_types}"
                            )
                elif "type" in pydantic_prop:
                    pydantic_type = pydantic_prop["type"]
                    if openapi_type and openapi_type != pydantic_type:
                        errors.append(
                            f"Property '{prop_name}' type mismatch: "
                            f"OpenAPI={openapi_type}, Pydantic={pydantic_type}"
                        )

        # Compare the required fields
        openapi_required = set(openapi_schema.get("required", []))
        pydantic_required = set(pydantic_schema.get("required", []))

        missing_required = openapi_required - pydantic_required
        if missing_required:
            errors.append(f"Missing required fields in Pydantic model: {missing_required}")

        extra_required = pydantic_required - openapi_required
        if extra_required:
            # Warning, not an error - it could be intentional
            errors.append(
                f"Extra required fields in Pydantic model (not in OpenAPI): {extra_required}"
            )

        return len(errors) == 0, errors

    def compare_property_types(
        self, openapi_type: str | None, pydantic_schema: dict[str, Any]
    ) -> bool:
        """
        Compare an OpenAPI type with a Pydantic property schema.

        Args:
            openapi_type: OpenAPI type (e.g. "string", "integer")
            pydantic_schema: Schema of the Pydantic property

        Returns:
            True if the types are compatible
        """
        if not openapi_type:
            return True

        # Handle anyOf for nullable types
        if "anyOf" in pydantic_schema:
            types = [t.get("type") for t in pydantic_schema["anyOf"] if "type" in t]
            return openapi_type in types

        # Direct comparison
        pydantic_type = pydantic_schema.get("type")
        return openapi_type == pydantic_type


class OpenAPISchemaComparator:
    """Compares OpenAPI schemas across multiple spec files."""

    @staticmethod
    def load_openapi_specs(spec_paths: Sequence[str | Path]) -> dict[str, OpenAPI]:
        """
        Load multiple OpenAPI specifications.

        Args:
            spec_paths: List of paths to the YAML files

        Returns:
            Dict mapping filename -> OpenAPI spec
        """
        specs = {}
        for spec_path in spec_paths:
            path = Path(spec_path)
            validator = OpenAPIValidator(path)
            specs[path.name] = validator.openapi_spec
        return specs

    @staticmethod
    def find_common_schemas(specs: dict[str, OpenAPI]) -> dict[str, list[str]]:
        """
        Find common schemas across multiple OpenAPI specs.

        Args:
            specs: Dict of OpenAPI specifications

        Returns:
            Dict mapping schema_name -> list of spec files that contain it
        """
        schema_locations = {}

        for spec_name, spec in specs.items():
            if not spec.components or not spec.components.schemas:
                continue

            for schema_name in spec.components.schemas.keys():
                if schema_name not in schema_locations:
                    schema_locations[schema_name] = []
                schema_locations[schema_name].append(spec_name)

        return schema_locations
