# TecnoAgro

Foliar Nutrition Management System for Crops

## 1. Introduction

TecnoAgro is a software platform designed to manage data related to foliar nutrition in crops. It helps farmers optimize nutrient usage and increase productivity. Data is sourced from drone images processed externally and complemented with information entered manually.

The system receives this data through an API and a web form, analyzes it, and stores it to generate personalized recommendations based on local nutrient parameters. This approach enables precise decision making, improving resource efficiency and agricultural performance.

## Importing Crops from CSV

To bulk create or update crops you can upload a CSV file using the following endpoint:

`POST /api/foliage/crops/csv/import`

Send the CSV as `multipart/form-data` with the field **file**. The file must have a header row with at least the column `name`:

```csv
name
Tomato
Potato
```

Existing crops will be updated by name and new names will be inserted. The JSON response includes the number of inserted and updated records.

## Media Upload Limits

- Configure `MEDIA_MAX_UPLOAD_SIZE` (e.g. `2G`, `512M`) in `.env` to align Flask's `MAX_CONTENT_LENGTH` with Nginx (`client_max_body_size`).
- Optional knobs: `MEDIA_UPLOAD_CHUNK_SIZE` (stream block size) and `MEDIA_UPLOAD_TMP_DIR` to move the temporary spool outside the main storage volume.
- After changing the limit regenerate `nginx.conf` with `./make_nginx.conf.sh <domain>` or restart Docker so that the proxy picks up the new value.
