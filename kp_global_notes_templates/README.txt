KP Global Notes templates
========================

Contents:
- templates/dashboard/base.html (existing base retained; it already exposes extra_head and extra_js blocks)
- templates/dashboard/notes/_styles.html (shared styling partial)
- templates/dashboard/notes/list.html
- templates/dashboard/notes/form.html
- templates/dashboard/notes/confirm_delete.html

Integration:
1. Copy the templates/ directory into your project's templates directory, merging with existing files.
2. These templates expect the view names:
   church:notes, church:note-create, church:note-update, church:note-delete.
3. List view context expected:
   notes, total_notes, categories, selected_category, search_query.
4. Form view uses a ModelForm with fields title, body, category, scripture, is_pinned.
5. The base template was not redesigned or overwritten because it already supports extra_head; each Notes page imports the shared CSS partial there, avoiding repeated styles.
6. The global dashboard stylesheet should provide the existing design tokens/classes used by the project, including --brand, --line, --text, --muted and .btn/.card.
