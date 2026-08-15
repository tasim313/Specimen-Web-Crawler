"""
Import-export resources for the pathology admin panel.

These resources define which model fields are included when importing or
exporting data via the Django admin (CSV, XLSX, and other formats supported
by ``django-import-export``).
"""

from import_export import resources
from import_export.fields import Field
from import_export.widgets import ForeignKeyWidget

from .models import Organ, Specimen


class OrganResource(resources.ModelResource):
    """Resource for importing/exporting ``Organ`` records.

    ``name`` is used as the import identifier so that CSV/Excel files can
    reference organs by their human-readable name.
    """

    class Meta:
        model = Organ
        fields = ("id", "name")
        export_order = ("id", "name")
        import_id_fields = ("name",)
        skip_unchanged = True


class SpecimenResource(resources.ModelResource):
    """Resource for importing/exporting ``Specimen`` records.

    The ``organ`` foreign key is resolved by name so that CSV/Excel files
    can reference organs using their human-readable name rather than a
    numeric primary key.
    """

    organ = Field(
        column_name="Organ Name",
        attribute="organ",
        widget=ForeignKeyWidget(Organ, field="name"),
    )

    class Meta:
        model = Specimen
        fields = (
            "id",
            "organ",
            "specimen_name",
            "site_name",
            "laterality",
            "specimen_type",
            "specimen_size",
            "procedure_name",
            "is_biopsy",
            "is_resection",
            "is_cytology",
            "is_histopathology",
            "is_ihc_applicable",
            "is_molecular_applicable",
            "source_site",
            "source_file",
            "created_at",
        )
        export_order = (
            "id",
            "organ",
            "specimen_name",
            "site_name",
            "laterality",
            "specimen_type",
            "specimen_size",
            "procedure_name",
            "is_biopsy",
            "is_resection",
            "is_cytology",
            "is_histopathology",
            "is_ihc_applicable",
            "is_molecular_applicable",
            "source_site",
            "source_file",
            "created_at",
        )
        import_id_fields = ("source_file",)
        skip_unchanged = True
        # ``created_at`` is auto-managed; allow it in export but not import.
        import_fields = (
            "id",
            "organ",
            "specimen_name",
            "site_name",
            "laterality",
            "specimen_type",
            "specimen_size",
            "procedure_name",
            "is_biopsy",
            "is_resection",
            "is_cytology",
            "is_histopathology",
            "is_ihc_applicable",
            "is_molecular_applicable",
            "source_site",
            "source_file",
        )
