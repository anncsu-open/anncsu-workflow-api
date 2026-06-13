"""Polyfactory factories for generating test data."""

from faker import Faker
from polyfactory.factories.pydantic_factory import ModelFactory

from app.models.workflows import (
    AccessoResult,
    AggiornaCoordinateOutput,
    CreaIndirizzoCompletoInput,
    CreaIndirizzoCompletoOutput,
    OdonimoResult,
    RicercaIndirizzoInput,
    RicercaIndirizzoOutput,
    SopprimiOdonimoInput,
    SopprimiOdonimoOutput,
)

# Disable model validation in factories to avoid deprecation warnings
ModelFactory.__check_model__ = False

fake = Faker("it_IT")  # Use Italian locale


# ============================================================================
# Custom providers for Italian-specific data
# ============================================================================


def codice_belfiore() -> str:
    """Generate a valid Italian Belfiore code (1 letter + 3 digits)."""
    return fake.random_uppercase_letter() + str(fake.random_int(min=100, max=999))


def denominazione_odonimo() -> str:
    """Generate an Italian odonimo denomination."""
    odonimi = [
        "ROMA",
        "MILANO",
        "TORINO",
        "NAPOLI",
        "VENEZIA",
        "GARIBALDI",
        "MAZZINI",
        "CAVOUR",
        "VITTORIO EMANUELE",
        "KENNEDY",
        "DANTE",
        "PETRARCA",
        "LEOPARDI",
    ]
    return fake.random_element(odonimi)


def dug() -> str:
    """Generate a Generic Urban Denomination (DUG)."""
    dugs = [
        "VIA",
        "PIAZZA",
        "CORSO",
        "VIALE",
        "VICOLO",
        "LARGO",
        "STRADA",
        "AUTOSTRADA",
    ]
    return fake.random_element(dugs)


def numero_civico() -> str:
    """Generate a civico number."""
    return str(fake.random_int(min=1, max=999))


def esponente_civico() -> str | None:
    """Generate an esponente for the civico number."""
    return fake.random_element([None, "A", "B", "C", "D", "BIS", "TER"])


def specificita() -> str | None:
    """Generate a specificità (color) for the civico."""
    return fake.random_element([None, "ROSSO", "NERO", "BLU", "VERDE"])


def coordinata_x() -> str:
    """Generate a valid X coordinate for Italy (6.0-18.0)."""
    return f"{fake.pyfloat(min_value=6.0, max_value=18.0, right_digits=7)}"


def coordinata_y() -> str:
    """Generate a valid Y coordinate for Italy (36.0-47.0)."""
    return f"{fake.pyfloat(min_value=36.0, max_value=47.0, right_digits=7)}"


def coordinata_z() -> str | None:
    """Generate an elevation in meters."""
    if fake.boolean(chance_of_getting_true=50):
        return str(fake.random_int(min=0, max=3000))
    return None


def metodo_rilevazione() -> str:
    """Generate a survey method (1-4)."""
    return str(fake.random_int(min=1, max=4))


def progressivo_nazionale() -> str:
    """Generate a progressivo nazionale."""
    return str(fake.random_int(min=1000000, max=9999999))


def data_italiana() -> str:
    """Generate a date in DD/MM/YYYY format."""
    date = fake.date_between(start_date="-2y", end_date="today")
    return date.strftime("%d/%m/%Y")


# ============================================================================
# Factories
# ============================================================================


class CreaIndirizzoCompletoInputFactory(ModelFactory[CreaIndirizzoCompletoInput]):
    """Factory for CreaIndirizzoCompletoInput."""

    __model__ = CreaIndirizzoCompletoInput

    @classmethod
    def codcom(cls) -> str:
        return codice_belfiore()

    @classmethod
    def denom_odonimo(cls) -> str:
        return denominazione_odonimo()

    @classmethod
    def dug(cls) -> str:
        return dug()

    @classmethod
    def numero_civico(cls) -> str:
        return numero_civico()

    @classmethod
    def data_validita(cls) -> str | None:
        return data_italiana() if fake.boolean(chance_of_getting_true=70) else None


class CreaIndirizzoCompletoOutputFactory(ModelFactory[CreaIndirizzoCompletoOutput]):
    """Factory for CreaIndirizzoCompletoOutput."""

    __model__ = CreaIndirizzoCompletoOutput

    @classmethod
    def success(cls) -> bool:
        return fake.boolean(chance_of_getting_true=80)

    @classmethod
    def progressivo_nazionale_odonimo(cls) -> str | None:
        return progressivo_nazionale() if fake.boolean(chance_of_getting_true=80) else None

    @classmethod
    def progressivo_civico(cls) -> str | None:
        return progressivo_nazionale() if fake.boolean(chance_of_getting_true=80) else None

    @classmethod
    def message(cls) -> str:
        return fake.sentence()

    @classmethod
    def errors(cls) -> list[str] | None:
        if fake.boolean(chance_of_getting_true=20):
            return [fake.sentence() for _ in range(fake.random_int(min=1, max=3))]
        return None


class AggiornaCoordinateOutputFactory(ModelFactory[AggiornaCoordinateOutput]):
    """Factory for AggiornaCoordinateOutput."""

    __model__ = AggiornaCoordinateOutput

    @classmethod
    def success(cls) -> bool:
        return fake.boolean(chance_of_getting_true=80)

    @classmethod
    def progressivo_civico(cls) -> str | None:
        return progressivo_nazionale() if fake.boolean(chance_of_getting_true=80) else None

    @classmethod
    def coordinate(cls) -> dict | None:
        if fake.boolean(chance_of_getting_true=80):
            return {
                "x": coordinata_x(),
                "y": coordinata_y(),
                "z": coordinata_z(),
                "metodo": metodo_rilevazione(),
            }
        return None

    @classmethod
    def message(cls) -> str:
        return fake.sentence()

    @classmethod
    def errors(cls) -> list[str] | None:
        if fake.boolean(chance_of_getting_true=20):
            return [fake.sentence() for _ in range(fake.random_int(min=1, max=3))]
        return None


class SopprimiOdonimoInputFactory(ModelFactory[SopprimiOdonimoInput]):
    """Factory for SopprimiOdonimoInput."""

    __model__ = SopprimiOdonimoInput

    @classmethod
    def codcom(cls) -> str:
        return codice_belfiore()

    @classmethod
    def denom_odonimo(cls) -> str:
        return denominazione_odonimo()

    @classmethod
    def data_soppressione(cls) -> str:
        return data_italiana()


class SopprimiOdonimoOutputFactory(ModelFactory[SopprimiOdonimoOutput]):
    """Factory for SopprimiOdonimoOutput."""

    __model__ = SopprimiOdonimoOutput

    @classmethod
    def success(cls) -> bool:
        return fake.boolean(chance_of_getting_true=80)

    @classmethod
    def odonimo_soppresso(cls) -> str | None:
        return (
            f"{dug()} {denominazione_odonimo()}"
            if fake.boolean(chance_of_getting_true=80)
            else None
        )

    @classmethod
    def progressivo_nazionale(cls) -> str | None:
        return progressivo_nazionale() if fake.boolean(chance_of_getting_true=80) else None

    @classmethod
    def accessi_presenti(cls) -> list[AccessoResult] | None:
        if fake.boolean(chance_of_getting_true=80):
            return [AccessoResultFactory.build() for _ in range(fake.random_int(min=0, max=5))]
        return None

    @classmethod
    def message(cls) -> str:
        return fake.sentence()

    @classmethod
    def errors(cls) -> list[str] | None:
        if fake.boolean(chance_of_getting_true=20):
            return [fake.sentence() for _ in range(fake.random_int(min=1, max=3))]
        return None


class RicercaIndirizzoInputFactory(ModelFactory[RicercaIndirizzoInput]):
    """Factory for RicercaIndirizzoInput."""

    __model__ = RicercaIndirizzoInput

    @classmethod
    def codcom(cls) -> str:
        return codice_belfiore()

    @classmethod
    def denom_odonimo(cls) -> str:
        return denominazione_odonimo()

    @classmethod
    def numero_civico(cls) -> str | None:
        return numero_civico() if fake.boolean(chance_of_getting_true=50) else None


class OdonimoResultFactory(ModelFactory[OdonimoResult]):
    """Factory for OdonimoResult."""

    __model__ = OdonimoResult

    @classmethod
    def prognaz(cls) -> str:
        return progressivo_nazionale()

    @classmethod
    def dug(cls) -> str:
        return dug()

    @classmethod
    def denomuff(cls) -> str:
        return denominazione_odonimo()

    @classmethod
    def denomloc(cls) -> str | None:
        return fake.city() if fake.boolean(chance_of_getting_true=30) else None

    @classmethod
    def denomlingua1(cls) -> str | None:
        return fake.sentence() if fake.boolean(chance_of_getting_true=10) else None

    @classmethod
    def denomlingua2(cls) -> str | None:
        return fake.sentence() if fake.boolean(chance_of_getting_true=5) else None


class AccessoResultFactory(ModelFactory[AccessoResult]):
    """Factory for AccessoResult."""

    __model__ = AccessoResult

    @classmethod
    def prognazacc(cls) -> str:
        return progressivo_nazionale()

    @classmethod
    def civico(cls) -> str | None:
        return numero_civico() if fake.boolean(chance_of_getting_true=90) else None

    @classmethod
    def esp(cls) -> str | None:
        return esponente_civico()

    @classmethod
    def specif(cls) -> str | None:
        return specificita()

    @classmethod
    def metrico(cls) -> str | None:
        return (
            str(fake.random_int(min=100, max=9999))
            if fake.boolean(chance_of_getting_true=30)
            else None
        )

    # coordX and coordY use mixedCase to match the ANNCSU OpenAPI field names
    @classmethod
    def coordX(cls) -> str | None:  # noqa: N802
        return coordinata_x() if fake.boolean(chance_of_getting_true=70) else None

    @classmethod
    def coordY(cls) -> str | None:  # noqa: N802
        return coordinata_y() if fake.boolean(chance_of_getting_true=70) else None

    @classmethod
    def quota(cls) -> str | None:
        return coordinata_z()

    @classmethod
    def metodo(cls) -> str | None:
        return metodo_rilevazione() if fake.boolean(chance_of_getting_true=70) else None


class RicercaIndirizzoOutputFactory(ModelFactory[RicercaIndirizzoOutput]):
    """Factory for RicercaIndirizzoOutput."""

    __model__ = RicercaIndirizzoOutput

    @classmethod
    def success(cls) -> bool:
        return fake.boolean(chance_of_getting_true=80)

    @classmethod
    def odonimi(cls) -> list[OdonimoResult]:
        count = fake.random_int(min=0, max=5)
        return [OdonimoResultFactory.build() for _ in range(count)]

    @classmethod
    def accessi(cls) -> list[AccessoResult]:
        count = fake.random_int(min=0, max=10)
        return [AccessoResultFactory.build() for _ in range(count)]

    @classmethod
    def message(cls) -> str:
        return fake.sentence()

    @classmethod
    def errors(cls) -> list[str] | None:
        if fake.boolean(chance_of_getting_true=20):
            return [fake.sentence() for _ in range(fake.random_int(min=1, max=3))]
        return None
