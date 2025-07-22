"""Utility class for CSV import and export operations."""

import csv
import io
import os
import tempfile


class CsvHandler:
    def export_to_csv(self, data):
        """Export a list of rows or dictionaries to a CSV formatted string.

        :param data: Iterable of dictionaries or lists representing CSV rows.
        :return: CSV data encoded as a string.
        """
        if data is None:
            raise ValueError("Input data cannot be None.")

        output = io.StringIO()
        # Using 'newline=""' to prevent blank rows in CSV on Windows
        writer = csv.writer(output)

        if not data:
            return ""

        if isinstance(data[0], dict):
            headers = list(data[0].keys())  # Ensure consistent order
            writer.writerow(headers)
            for row_dict in data:
                # Ensure values are written in the same order as headers
                writer.writerow([row_dict.get(header, "") for header in headers])
        elif isinstance(data[0], list):
            for row_list in data:
                writer.writerow(row_list)
        else:
            raise ValueError("Data must be a list of lists or a list of dictionaries.")

        return output.getvalue()

    def import_from_csv(self, csv_file_path, has_header=True):
        """Read a CSV file from disk and return its contents.

        :param csv_file_path: Path to the CSV file on the filesystem.
        :param has_header: If ``True``, the first row is treated as headers and
            each data row is returned as a dictionary. If ``False``, rows are
            returned as lists.
        :return: List of dictionaries or lists containing the CSV data.
        """
        try:
            with open(csv_file_path, mode="r", newline="", encoding="utf-8") as csvfile:
                reader = csv.reader(csvfile)
                if has_header:
                    try:
                        headers = next(reader)
                        # Handle cases where the CSV is empty or has only headers
                        if (
                            not headers
                        ):  # Check if headers list itself is empty (e.g. empty first line)
                            return []
                        data = [dict(zip(headers, row)) for row in reader]
                    except StopIteration:  # Handles empty file or file with only header
                        return []  # or appropriate response for empty data with header
                else:
                    data = [row for row in reader]

                # if file was empty or only contained a header (and data became empty list)
                # or if has_header=False and file was empty
                if (
                    not data and has_header and not headers
                ):  # Re-check for empty after StopIteration for header
                    pass  # If headers were present but no data, data is already []
                elif (
                    not data and not has_header
                ):  # If no header expected and no data rows
                    return []

                return data
        except FileNotFoundError:
            raise FileNotFoundError(f"The file {csv_file_path} was not found.")
        except csv.Error as e:
            # More specific error for empty CSV or header-only CSV if needed
            if "iterator should return strings, not None" in str(e) and has_header:
                # This can happen if a file has a header but no data rows,
                # and csv.DictReader is used internally or similar logic.
                # Our current list comprehension [dict(zip(headers, row)) for row in reader] handles this.
                # If headers were read but no rows followed, data will be [].
                return []
            raise csv.Error(f"Error parsing CSV file: {e}")
        except Exception as e:
            # Catch any other unexpected errors during file processing
            raise ValueError(
                f"An unexpected error occurred while processing the CSV file: {e}"
            )

    def handle_csv_upload(self, uploaded_file_object, has_header=True):
        """Process a CSV uploaded through a web interface.

        The uploaded file is stored in a temporary location and then parsed
        using :meth:`import_from_csv`.

        :param uploaded_file_object: File-like object or Werkzeug ``FileStorage``
            representing the uploaded CSV file. It must provide either a
            ``save`` method or a ``read`` method.
        :param has_header: Flag indicating whether the CSV file includes a
            header row.
        :return: List of dictionaries or lists as produced by
            :meth:`import_from_csv`.
        """
        if not uploaded_file_object:
            raise ValueError("Uploaded file object cannot be None.")

        temp_file_path = None
        try:
            # Create a named temporary file so we can pass its path to import_from_csv
            # delete=False is important because we pass the path to another function,
            # and on some OS (like Windows), the file cannot be opened by another process
            # if it's still kept open by this process, or if delete=True and we close it.
            # We will manually clean it up in the finally block.
            # Using 'w+b' to handle binary file uploads directly if 'save' writes binary,
            # or if 'read' returns bytes.
            with tempfile.NamedTemporaryFile(mode="w+b", delete=False) as temp_file:
                temp_file_path = temp_file.name

                # If the uploaded_file_object has a save method (e.g., Flask's FileStorage)
                if hasattr(uploaded_file_object, "save"):
                    # The save method might write directly to the path or to the file object.
                    # If it writes to the path, temp_file (opened here) might not be needed directly for writing.
                    # For Werkzeug FileStorage, `save` takes a dst, which can be a path or a stream.
                    # Passing temp_file_path ensures it works as expected.
                    uploaded_file_object.save(temp_file_path)
                    # After `save`, the file at temp_file_path contains the data.
                    # `import_from_csv` will then open it in text mode.
                # Otherwise, assume it's a readable file-like object (e.g., Django's UploadedFile)
                elif hasattr(uploaded_file_object, "read"):
                    # Read content. It could be bytes or string.
                    content = uploaded_file_object.read()

                    # temp_file is opened in binary mode ('w+b').
                    # If content is string, encode it to bytes.
                    if isinstance(content, str):
                        # Use UTF-8 as a common encoding.
                        # Consider making encoding a parameter if various encodings are expected.
                        content = content.encode("utf-8")

                    temp_file.write(content)
                    # Ensure data is flushed to disk before import_from_csv reads it.
                    temp_file.flush()
                    os.fsync(temp_file.fileno())
                else:
                    # If the object is neither a FileStorage-like object nor a readable stream.
                    raise ValueError(
                        "Uploaded file object must have a 'save' method or be readable (have a 'read' method)."
                    )

            # Now that the temp file is populated (either by 'save' or 'write'), process it.
            # import_from_csv expects a file path and handles opening it in text mode with utf-8.
            return self.import_from_csv(temp_file_path, has_header=has_header)
        finally:
            # Clean up the temporary file if it was created.
            if temp_file_path and os.path.exists(temp_file_path):
                os.remove(temp_file_path)
