---
name: work-starters
description: Start a pending project in the shared work format without selecting a protocol or creating dummy work.
---
# Minimal project authoring

Use the host's supported create-and-open operation. With no selected template, it supplies the versioned `work.blank_project` resource. Omitted title becomes `Untitled project`; the host allocates the identity. No tasks, execution manager, protocol, reviews or budgets are prefilled.

Fill in useful information as it becomes known, using the issued sheet's fields/help. Empty planning sections are valid while pending. Use local aliases for genuinely new tasks and documents according to the normal sheet help. Do not invent an outcome or dummy task to satisfy formatting. Do not change protected IDs or generated actual state.

The pending project is saved immediately. On-disk edits autosave as ordinary drafts. Manual finish or the normal idle timeout checks in valid edits, closes/releases the editing session and removes its registered temporary files. The project and saved history remain; reopen it through its canonical reference. Malformed edits are preserved as rejected drafts with a useful diagnostic, not silently lost.

Creating or saving is not admission or dispatch. Select an existing protocol/template explicitly when its structure is useful; honour its actual required parameters and the project's authority. A blank project requires neither Megado nor another specialist.
