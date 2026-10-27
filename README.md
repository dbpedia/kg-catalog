# LOD Next Gen repository

## Adding KG dumps hosted on Kaggle

For a KG dump hosted on Kaggle, use the direct API download URL in the
distribution's `file` field in `knowledge-graphs/<kg-id>/metadata.yaml` or in the
**KG Content (Artifacts, Versions and Distributions)** field of the New KG
submission form.

The URL format is:

```text
https://www.kaggle.com/api/v1/datasets/download/<owner>/<dataset-slug>?filename=<filename>
```

For example:

```yaml
distributions:
  - file: https://www.kaggle.com/api/v1/datasets/download/ammaryousaf45/e-obs-climate-data?filename=eobs_climate_kg_2015_2019_20251217_173418.ttl
    format: ttl
```

Do not use the Kaggle dataset browser URL as a distribution's `file` URL:

```text
https://www.kaggle.com/datasets/ammaryousaf45/e-obs-climate-data?select=eobs_climate_kg_2015_2019_20251217_173418.ttl
```

The browser URL opens the dataset page with a file selected; the API download URL
points to the file download. Keep the same owner, dataset slug, and filename when
converting the URL, and replace `?select=` with `?filename=`.


## KG Domain Classification (Modernized LOD cloud domains)

### 1. `Cross-domain`
General-purpose knowledge graphs that integrate multiple subjects or do not belong to a single specific domain. Includes encyclopedic datasets and hub-like resources that connect diverse domains.

### 2. `Geography & Environment`
Datasets related to places, spatial information, and the natural environment. Includes geography, GIS, climate data, biodiversity, earth observation, and sustainability-related information.

### 3. `Government & Public Sector`
Open government data and public administration information. Includes laws, regulations, statistics, census data, public services, and policy-related datasets.

### 4. `Life Sciences & Health`
Biomedical and health-related knowledge. Includes medicine, clinical data, genomics, pharmaceuticals, epidemiology, and public health information.

### 5. `Economy, Industry & Infrastructure`
Economic systems and real-world operational networks. Includes finance, markets, companies, industry, manufacturing, energy systems, transport, logistics, and infrastructure.

### 6. `Publications, Education & Research`
Scholarly and educational knowledge systems. Includes scientific publications, bibliographic databases, research data, academic institutions, and open science infrastructures.

### 7. `Media, Culture & Entertainment`
Content and cultural knowledge domains. Includes news, music, film, television, publishing, journalism, cultural heritage, museums, and humanities datasets.

### 8. `Linguistics, Social & Digital Knowledge Systems`
Language resources and digital interaction systems. Includes linguistics, ontologies, social networks, user-generated content, software systems, and digital/semantic infrastructure.
