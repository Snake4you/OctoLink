# coding=utf-8
from setuptools import setup, find_packages

plugin_identifier = "prusalink_bridge"
plugin_package = "octoprint_prusalink_bridge"
plugin_name = "OctoPrint-PrusaLink-Bridge"
plugin_version = "0.1.0"
plugin_description = (
    "Mirrors telemetry, temperatures and print job status from PrusaLink "
    "(MK3.5, MK4, XL, CORE One) to OctoPrint for third-party plugins like Obico."
)
plugin_author = "snake"
plugin_author_email = "developer@octolink.local"
plugin_url = "https://github.com/snake/OctoPrint-PrusaLink-Bridge"
plugin_license = "AGPLv3"

plugin_requires = [
    "OctoPrint",
    "requests>=2.20.0",
]

plugin_additional_data = {}
plugin_additional_packages = []
plugin_ignored_packages = []
additional_setup_parameters = {}

setup_parameters = {
    "name": plugin_name,
    "version": plugin_version,
    "description": plugin_description,
    "author": plugin_author,
    "author_email": plugin_author_email,
    "url": plugin_url,
    "license": plugin_license,
    "packages": find_packages(where=".", exclude=["tests*", "docs*"]),
    "package_data": {
        plugin_package: [
            "templates/*",
            "static/js/*",
            "static/css/*",
        ]
    },
    "include_package_data": True,
    "install_requires": plugin_requires,
    "python_requires": ">=3.7, <4",
    "entry_points": {
        "octoprint.plugin": [
            f"{plugin_identifier} = {plugin_package}"
        ]
    },
}

if __name__ == "__main__":
    setup(**setup_parameters)
