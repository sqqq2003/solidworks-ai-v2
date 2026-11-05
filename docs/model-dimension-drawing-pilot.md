# Existing-model dimension import pilot

Standalone-part trial requests may explicitly set `import_model_dimensions: true`
and `required_model_dimensions: ["D1@Feature", ...]`. Names must come from a
reviewed native parameter inventory. Assembly import is rejected before launch.

The executor reads source values, calls `InsertModelAnnotations3` once, then
checks native display dimensions after layout and save/reopen. It never writes
dimension values or replaces numbers with notes. Missing dimensions, numeric
overrides and unconfirmed local display units remain `dimensions_pending`;
generated PDF/SLDDRW files alone cannot satisfy the dimension evidence gate.

Optional `deduplicate_model_dimensions: true` keeps one presentation per full
model-dimension identity. `dimension_view_preferences` may select a standard
view for each required parameter. Redundant drawing annotations are hidden
with `IAnnotation.Visible=3`, never deleted or numerically changed. Conflicting
values are not hidden. Hidden states and kept values must survive save/reopen;
the evidence gate also rejects duplicate visible model identities.

Optional `correlate_model_dimensions_pdf: true` requires one-to-one native
value/XY-to-PDF-word-bounds matching on one unrotated sheet. `pdfplumber` extracts
real text rectangles; glyph matrices determine horizontal/vertical reading
order. Missing/ambiguous matches, text collisions, frame escapes and title-block
intrusions remain `pdf_dimensions_pending`. Independent evidence inspection
re-extracts the PDF; changed native rows or PDF hashes invalidate the binding.

Native values use metres/radians; view outlines are not part dimensions.
OCR, arbitrary-angle pages/text and complex dimension text need review.
Tolerances, material and title-block fields still require engineering review.
This pilot grants no manufacturing approval.

API references: [InsertModelAnnotations3](https://help.solidworks.com/2016/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IDrawingDoc~InsertModelAnnotations3.html),
[GetOverride](https://help.solidworks.com/2025/English/api/sldworksapi/SOLIDWORKS.Interop.sldworks~SOLIDWORKS.Interop.sldworks.IDisplayDimension~GetOverride.html).
