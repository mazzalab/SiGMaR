import os
import shutil

import dash
from dash import Input, Output, State, ALL, ctx
from config import DEFAULT_OUTPUT_ROOT


def register_navigation_callback(app):
    @app.callback(
        [Output("page-content", "children"),
         Output("selected_study_persistent", "data"),
         Output("page-content", "style"),
         Output("url", "pathname"),
         Output("nav_source_persistent", "data")],
        [Input("url", "pathname"),
         Input({"type": "nav_btn", "index": ALL}, "n_clicks"),
         Input({"type": "study_open_btn", "study": ALL}, "n_clicks"),
         Input({"type": "study_delete_btn", "study": ALL}, "n_clicks")],
        [State("folder_name_persistent", "data"),
         State("tumor_type_persistent", "data"),
         State("counts_gene_column_persistent", "data"),
         State("clinical_sample_column_persistent", "data"),
         State("selected_study_persistent", "data"),
         State("nav_source_persistent", "data")],
        prevent_initial_call=False
    )
    def display_page(pathname, nav_clicks, open_clicks, delete_clicks, folder, tumor_type, counts_gene_column, clinical_sample_column, selected_study, nav_source):
        from callbacks.callbacks_analysis import get_clean_path

        trig_id = ctx.triggered_id

        def selected_output(study=None):
            return study

        def content_style(kind="home"):
            top_padding = {
                "home": "11rem",
                "upload": "18rem",
                "analysis": "18rem",
                "clinical_association": "18rem",
                "studies": "11rem",
                "report": "11rem",
                "about": "11rem",
                "documentation": "11rem",
                "contact": "11rem",
            }.get(kind, "11rem")
            return {
                "maxWidth": "100%",
                "paddingTop": top_padding,
                "paddingBottom": "8rem",
                "minHeight": "100%",
            }

        def studies_page():
            from layouts.layout_studies import serve_studies_layout

            return serve_studies_layout(DEFAULT_OUTPUT_ROOT), selected_output(None), content_style("studies"), "/results", None

        def home_page():
            from layouts.layout_home import serve_home_layout

            return serve_home_layout(), selected_output(None), content_style("home"), "/", None

        def upload_page(reset_folder=False):
            from layouts.layout_upload import serve_layout_upload

            folder_value = None if reset_folder else folder
            return serve_layout_upload(tumor_type, DEFAULT_OUTPUT_ROOT, folder_value, counts_gene_column, clinical_sample_column), selected_output(None), content_style("upload"), "/upload", None

        def analysis_page():
            from layouts.layout_analysis import serve_layout_analysis

            return serve_layout_analysis(tumor_type), selected_output(None), content_style("analysis"), "/analysis", None

        def clinical_association_page():
            from layouts.layout_clinical_association import serve_layout_clinical_association

            return serve_layout_clinical_association(), selected_output(None), content_style("clinical_association"), "/clinical-association", None

        def report_page(study_name, active_tab="table"):
            from layouts.layout_results import render_report_layout

            # Every study always lives under DEFAULT_OUTPUT_ROOT - the output
            # location is no longer user-editable (see layout_upload.py's
            # Output Location card) precisely so this never has to guess
            # between a default and some session-remembered custom root.
            out_dir = os.path.join(DEFAULT_OUTPUT_ROOT, study_name)
            return render_report_layout(out_dir, tumor_type, study_name=study_name, active_tab=active_tab), selected_output(study_name), content_style("report"), "/results/report", None

        def about_page():
            from layouts.layout_about import serve_layout_about

            return serve_layout_about(), selected_output(None), content_style("about"), "/about", None

        def documentation_page():
            from layouts.layout_documentation import serve_layout_documentation

            return serve_layout_documentation(), selected_output(None), content_style("documentation"), "/documentation", None

        def contact_page():
            from layouts.layout_contact import serve_layout_contact

            return serve_layout_contact(), selected_output(None), content_style("contact"), "/contact", None

        def route_from_path():
            if pathname in (None, "", "/"):
                return home_page()
            if pathname in ("/report", "/results/report") and selected_study:
                return report_page(selected_study)
            if nav_source != "app":
                return home_page()
            if pathname == "/upload":
                return upload_page()
            if pathname == "/analysis":
                return analysis_page()
            if pathname == "/clinical-association":
                return clinical_association_page()
            if pathname in ("/studies", "/results"):
                return studies_page()
            if pathname == "/about":
                return about_page()
            if pathname == "/documentation":
                return documentation_page()
            if pathname == "/contact":
                return contact_page()
            return home_page()

        if trig_id is None:
            raise dash.exceptions.PreventUpdate

        if trig_id == "url":
            return route_from_path()

        if isinstance(trig_id, dict) and trig_id.get("type") == "nav_btn":
            button_index = trig_id.get("index")
            if button_index == "new_analysis_btn":
                return (*upload_page(reset_folder=True)[:-1], "app")
            if button_index == "clinical_association_btn":
                return (*clinical_association_page()[:-1], "app")
            if button_index == "results_btn":
                return (*studies_page()[:-1], "app")
            if button_index == "home_btn":
                return (*home_page()[:-1], "app")
            if button_index == "about_btn":
                return (*about_page()[:-1], "app")
            if button_index == "documentation_btn":
                return (*documentation_page()[:-1], "app")
            if button_index == "contact_btn":
                return (*contact_page()[:-1], "app")
            # Home page's own "Launch your analysis"/"For more info"/"About Us"/
            # "Contact Us" quick links (layout_home.py) - separate ids from the
            # top-nav's new_analysis_btn/about_btn/documentation_btn/contact_btn
            # (duplicate-id collision otherwise, since the top nav renders on
            # every page), routed here to the same pages.
            if button_index == "home_upload_link":
                return (*upload_page()[:-1], "app")
            if button_index == "home_documentation_link":
                return (*documentation_page()[:-1], "app")
            if button_index == "home_about_link":
                return (*about_page()[:-1], "app")
            if button_index == "home_contact_link":
                return (*contact_page()[:-1], "app")
            if button_index == "back_to_studies_btn":
                return (*studies_page()[:-1], "app")
            if button_index == "back_to_home_btn":
                return (*home_page()[:-1], "app")
            if button_index == "back_to_upload_btn":
                return (*upload_page()[:-1], "app")
            if button_index == "back_to_results_btn":
                return (*studies_page()[:-1], "app")
            if button_index == "analysis_results_btn":
                study_name = selected_study if selected_study else folder
                if study_name:
                    return (*report_page(study_name, active_tab="table")[:-1], "app")
                return (*studies_page()[:-1], "app")
            if button_index == "ca_results_btn":
                study_name = selected_study if selected_study else folder
                if study_name:
                    return (*report_page(study_name, active_tab="clinical-association")[:-1], "app")
                return (*studies_page()[:-1], "app")
            if button_index == "next_btn":
                return (*analysis_page()[:-1], "app")

        if isinstance(trig_id, dict) and trig_id.get("type") == "study_open_btn":
            if not open_clicks or max([c or 0 for c in open_clicks]) <= 0:
                return dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update
            study_name = trig_id.get("study")
            if study_name:
                return (*report_page(study_name, active_tab="table")[:-1], "app")
            return studies_page()

        if isinstance(trig_id, dict) and trig_id.get("type") == "study_delete_btn":
            if not delete_clicks or max([c or 0 for c in delete_clicks]) <= 0:
                return dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update
            study_name = trig_id.get("study")
            if study_name:
                study_path = os.path.join(DEFAULT_OUTPUT_ROOT, study_name)
                if os.path.isdir(study_path):
                    shutil.rmtree(study_path, ignore_errors=True)
            return studies_page()

        return dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update

    # The top nav's dbc.NavLink active="exact"/"partial" props (config.py's
    # create_nav_bar) only resolve dbc's built-in auto-highlighting once, at
    # first render - the nav bar is a persistent component that never gets
    # recreated across SPA navigations (only page-content swaps), so it never
    # re-evaluates which link matches the current path afterward. This
    # callback does that explicitly instead, on every pathname change
    # (including the ones from nav_btn-triggered clicks - see display_page
    # above - not just real browser navigation), so the highlighted nav item
    # always matches where you actually are.
    NAV_PATH_MAP = [
        ("home_btn", lambda p: p == "/"),
        ("new_analysis_btn", lambda p: p == "/upload"),
        ("clinical_association_btn", lambda p: p == "/clinical-association"),
        ("results_btn", lambda p: p.startswith("/results") or p.startswith("/studies")),
        ("about_btn", lambda p: p == "/about"),
        ("documentation_btn", lambda p: p == "/documentation"),
        ("contact_btn", lambda p: p == "/contact"),
    ]

    @app.callback(
        [Output({"type": "nav_btn", "index": index}, "active") for index, _ in NAV_PATH_MAP],
        Input("url", "pathname"),
    )
    def sync_nav_active(pathname):
        pathname = pathname or "/"
        return tuple(matches(pathname) for _, matches in NAV_PATH_MAP)
