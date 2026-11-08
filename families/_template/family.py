"""Skeleton for a new document family.

The registry skips this folder because its name starts with an underscore.
Copy the folder to families/<your_family>/, remove the leading underscore, and
implement DocumentFamily. Then add the family name to enabled_families in
config/settings.yaml.

A working example is families/property_tax/. Phase 7 documents the steps in
docs/ADDING_A_FAMILY.md. Do not import this module from core.

Outline (kept as comments so this file registers no family):

# class ExampleFamily(DocumentFamily):
#     name = "example"
#     version = "0.1.0"
#
#     def document_types(self):
#         return []
#
#     def extraction_prompt(self, doc_type):
#         return ""
#
#     def models(self):
#         return []
#
#     def persist(self, extraction_result, session):
#         return None
#
#     def rules(self):
#         return []
#
#     def feature_frame(self, session):
#         return None
#
#     def generator(self):
#         return None
"""
