# Source Coverage

The initial source target is the public ResDAC CMS Data catalog. The pipeline
first inventories source pages and linked assets, then archives the source
material before extracting metadata.

## Current Initial Source

Primary entry points:

- https://resdac.org/cms-data?page=0
- https://resdac.org/cms-data?page=1
- https://resdac.org/cms-data?page=2
- https://resdac.org/cms-data?page=3
- https://resdac.org/cms-data?page=4

The inventory crawler follows discovered dataset pages, documentation pages, and
linked assets from those listings.

## Preserved Asset Types

The archive pipeline is designed to preserve public documentation assets such
as:

- HTML pages.
- PDFs.
- XLSX files.
- CSV files.
- Images and attachments.

## Future Source Families

Potential future source families include:

- CMS documentation.
- CCW documentation.
- TAF technical specifications.
- VRDC resources.
- Medicare Advantage encounter documentation.
- Medicaid technical documentation.

Future source additions should preserve the same core guarantees: archive first,
record provenance, then extract structured metadata.
