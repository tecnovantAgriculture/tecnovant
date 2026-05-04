"""
Custom Route Lister View for Flask routes
module for Yet Another Flask Survival Kit (YAFSK)

Author:
    Johnny De Castro <j@jdcastro.co>

Copyright:
    (c) 2024 - 2025 Johnny De Castro. All rights reserved.

License:
    Apache License 2.0 - http://www.apache.org/licenses/LICENSE-2.0

"""

# Python standard library imports
from typing import Dict, List, Union

# Third party imports
from flask import current_app, json
from flask.views import MethodView


class RouteLister(MethodView):
    """
    View for listing all application routes with their documentation
    """

    def get(self):
        """
        Lists all application routes with their documentation
        :return: JSON with list of routes
        """
        output = [
            self._get_endpoint_info(rule)
            for rule in current_app.url_map.iter_rules()
            if rule.endpoint != "static"
        ]
        return current_app.response_class(
            response=json.dumps(output, ensure_ascii=False, indent=2),
            status=200,
            mimetype="application/json; charset=utf-8",
        )

    def _get_endpoint_info(self, rule) -> Dict[str, Union[str, List[str], Dict]]:
        """
        Retrieves information about a specific endpoint
        :param rule: URL rule object
        :return: Dictionary with endpoint information
        """
        endpoint_info = {
            "endpoint": rule.endpoint,
            "url": rule.rule,
            "methods": ",".join(rule.methods),
            "options": {arg: f"[{arg}]" for arg in rule.arguments},
            "parameters": [],
            "response_codes": [],
            "documentation": "",
            "method_docs": {},
        }
        func = current_app.view_functions.get(rule.endpoint)
        if func:
            endpoint_info.update(self._extract_docs(func))

        return endpoint_info

    def _extract_docs(self, func) -> Dict[str, Union[str, List[str], Dict]]:
        """
        Extracts documentation from a function or class
        :param func: View function or class
        :return: Dictionary with extracted documentation data
        """
        docstring = self._get_docstring(func)
        if not docstring:
            return {"documentation": "No documentation available"}

        general_description, general_params, general_responses, method_docs = (
            self._parse_docstring(docstring)
        )

        if hasattr(func, "view_class"):
            view_class = func.view_class
            docstring = view_class.__doc__
            method_docs.update(self._get_method_docs(view_class, func.methods or []))

        return {
            "documentation": general_description,
            "parameters": general_params,
            "response_codes": general_responses,
            "method_docs": method_docs or None,
        }

    @staticmethod
    def _get_docstring(func):
        """
        Safely retrieves the docstring from a function or class
        :param func: View function or class
        :return: Docstring or empty string
        """
        docstring = func.__doc__
        return docstring.strip() if docstring else ""

    from typing import Dict, List, Tuple

    @staticmethod
    def _parse_docstring(
        docstring: str,
    ) -> Tuple[str, List[str], List[str], Dict[str, Dict[str, List[str]]]]:
        """
        Parses the docstring for general and method-specific documentation.

        :param docstring: Raw docstring
        :return: Tuple with parsed general description, parameters, response codes, and method documentation.
        """
        lines = docstring.split("\n")
        general_description, general_params, general_responses, method_docs = (
            [],
            [],
            [],
            {},
        )

        for line in lines:
            line_stripped = line.strip()
            if line_stripped.startswith(":param"):
                general_params.append(line_stripped.replace(":param", "").strip())
            elif line_stripped.startswith(":status"):
                general_responses.append(line_stripped.replace(":status", "").strip())
            else:
                general_description.append(line_stripped)

        return (
            "\n".join(general_description).strip(),
            general_params,
            general_responses,
            method_docs,
        )

    def _get_method_docs(self, view_class, methods) -> Dict[str, Dict[str, List[str]]]:
        """
        Retrieves documentation for each method in a view class
        :param view_class: View class
        :param methods: List of HTTP methods
        :return: Dictionary with method documentation
        """
        method_docs = {}
        for method in methods:
            method_lower = method.lower()
            method_func = getattr(view_class, method_lower, None)
            if method_func:
                method_docstring = method_func.__doc__
                if method_docstring:
                    _, method_params, method_responses, _ = self._parse_docstring(
                        method_docstring
                    )
                    method_docs[method] = {
                        "parameters": method_params,
                        "response_codes": method_responses,
                    }
        return method_docs
