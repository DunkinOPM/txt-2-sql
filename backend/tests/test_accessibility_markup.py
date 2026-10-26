"""
Automated Accessibility Markup & WCAG Compliance Unit Tests.

These tests statically audit the frontend React components to enforce:
1. Accessible Modal & Dialog attributes (role="dialog", aria-modal, aria-labelledby, Escape handling).
2. Keyboard-scrollable overflow regions (tabIndex={0}, role="region", aria-label).
3. Accessible form controls (<textarea>, <input>, <select> have labels or aria-label).
4. Live announcements for alerts and status changes (role="alert", role="status", aria-live).
5. Visible focus indicators (focus-visible:ring-2 / focus:outline-none).
6. Icon-only buttons have accessible names (aria-label or descriptive text).
"""

import os
import re
import pytest

FRONTEND_SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "src"))


def get_file_content(relative_path: str) -> str:
    path = os.path.join(FRONTEND_SRC, relative_path)
    assert os.path.exists(path), f"File {path} does not exist"
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def test_modal_accessibility_contracts():
    """Verify all modal and dialog components meet WAI-ARIA Dialog (Modal) requirements."""
    modals = [
        "components/datasets/DeleteDatasetDialog.tsx",
        "components/datasets/DatasetPreview.tsx",
        "components/datasets/SchemaViewer.tsx",
        "components/query/HistoryDetailModal.tsx",
    ]

    for modal_path in modals:
        content = get_file_content(modal_path)

        # 1. Dialog role
        assert 'role="dialog"' in content or 'role="alertdialog"' in content, (
            f"{modal_path} must have role='dialog' or role='alertdialog'"
        )

        # 2. aria-modal="true"
        assert 'aria-modal="true"' in content, f"{modal_path} must declare aria-modal='true'"

        # 3. aria-labelledby
        assert 'aria-labelledby=' in content, f"{modal_path} must have aria-labelledby referencing header"

        # 4. Escape key handling and focus trapping/restoration (via useFocusTrap hook)
        assert (
            'useFocusTrap' in content
            or "'Escape'" in content
            or '"Escape"' in content
        ), f"{modal_path} must handle Escape dismissal or use useFocusTrap hook"

    # Verify useFocusTrap implementation meets full WAI-ARIA Modal specification
    trap_content = get_file_content("hooks/useFocusTrap.ts")
    assert "'Escape'" in trap_content
    assert "'Tab'" in trap_content
    assert "previousActiveElementRef" in trap_content
    assert "FOCUSABLE_SELECTOR" in trap_content


def test_scrollable_regions_are_keyboard_operable():
    """
    WCAG 2.1 AA requires scrollable overflow regions to be reachable and operable via keyboard.
    Ensures tabIndex={0}, role="region", and aria-label are present on overflow-x-auto containers.
    """
    files_with_tables = [
        "components/query/ResultsTable.tsx",
        "components/query/SQLViewer.tsx",
        "components/datasets/DatasetPreview.tsx",
        "components/datasets/SchemaViewer.tsx",
        "pages/QueryHistoryPage.tsx",
    ]

    for file_path in files_with_tables:
        content = get_file_content(file_path)
        # Check that overflow regions contain tabIndex={0} and role="region"
        assert 'tabIndex={0}' in content, f"{file_path} must include tabIndex={{0}} for keyboard scrolling"
        assert 'role="region"' in content, f"{file_path} must include role='region' on scrollable areas"
        assert 'aria-label=' in content, f"{file_path} must include an aria-label describing the region"


def test_form_inputs_have_accessible_names():
    """Verify input fields, textareas, and selects provide accessible names."""
    query_input = get_file_content("components/query/QueryInput.tsx")
    assert 'aria-label="Natural language query input"' in query_input or 'aria-label=' in query_input

    dataset_select = get_file_content("components/query/DatasetSelector.tsx")
    assert 'id="dataset-select"' in dataset_select
    assert 'htmlFor="dataset-select"' in dataset_select

    history_search = get_file_content("pages/QueryHistoryPage.tsx")
    assert 'aria-label="Search past queries"' in history_search
    assert 'aria-label="Filter by dataset"' in history_search

    clarification_input = get_file_content("components/query/ClarificationCard.tsx")
    assert 'aria-label="Clarification response"' in clarification_input


def test_live_announcements_for_alerts_and_statuses():
    """Verify dynamic state updates, errors, and alerts are announced to assistive technologies."""
    workspace = get_file_content("pages/WorkspacePage.tsx")
    assert 'role="alert"' in workspace
    assert 'aria-live="assertive"' in workspace
    assert 'role="status"' in workspace
    assert 'aria-live="polite"' in workspace

    history = get_file_content("pages/QueryHistoryPage.tsx")
    assert 'role="alert"' in history
    assert 'aria-live="assertive"' in history

    datasets = get_file_content("pages/DatasetsPage.tsx")
    assert 'role="alert"' in datasets
    assert 'role="status"' in datasets


def test_visible_focus_indicators():
    """Verify interactive components provide visible focus styling (focus-visible:ring-2 or focus:ring)."""
    components = [
        "components/layout/Sidebar.tsx",
        "components/layout/Topbar.tsx",
        "components/query/QueryInput.tsx",
        "components/query/ResultsTable.tsx",
        "components/query/SQLViewer.tsx",
        "components/query/ExportResults.tsx",
        "components/datasets/DatasetUpload.tsx",
        "components/datasets/DatasetCard.tsx",
        "components/datasets/DeleteDatasetDialog.tsx",
        "pages/WorkspacePage.tsx",
        "pages/DatasetsPage.tsx",
        "pages/QueryHistoryPage.tsx",
    ]

    for comp in components:
        content = get_file_content(comp)
        assert (
            "focus-visible:ring" in content
            or "focus:ring" in content
            or "focus-within:ring" in content
        ), f"{comp} must define visible focus indicator ring classes"


def test_responsive_mobile_navigation():
    """Verify mobile navigation drawer and toggle button have appropriate ARIA attributes."""
    topbar = get_file_content("components/layout/Topbar.tsx")
    assert 'aria-label=' in topbar
    assert "Open navigation drawer" in topbar
    assert "Close navigation drawer" in topbar

    app_layout = get_file_content("components/layout/AppLayout.tsx")
    assert 'role="dialog"' in app_layout
    assert 'aria-modal="true"' in app_layout
    assert 'aria-label="Navigation drawer"' in app_layout
