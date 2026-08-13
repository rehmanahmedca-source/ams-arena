"""pages — split from import_export.py."""
from ._common import *  # noqa

@import_export_bp.route('/full_raw_import', methods=['POST'])
@login_required
def full_raw_import():
    # ===== PANDAS DEPENDENCY CHECK =====
    if not _validate_pandas_installed():
        flash('CRITICAL: pandas library is not installed. Run: pip install pandas>=2.3.3', 'danger')
        return redirect(url_for('import_export.import_export_page'))
    # ===== END DEPENDENCY CHECK =====
    
    if not _full_raw_import_enabled():
        flash('Full raw import is disabled by safety toggle.', 'warning')
        return redirect(url_for('import_export.import_export_page'))

    if current_user.role not in ['admin', 'root']:
        flash('Only admin or root can run full raw import.', 'danger')
        return redirect(url_for('import_export.import_export_page'))

    file = request.files.get('file')
    if not file:
        flash('No file uploaded for full raw import.', 'danger')
        return redirect(url_for('import_export.import_export_page'))

    mode = (request.form.get('mode') or 'append').strip().lower()
    if mode not in ['append', 'replace_tenant_data']:
        mode = 'append'
    try:
        scope_ctx = _resolve_scope_context(
            scope_raw=request.form.get('scope'),
            tenant_id_raw=request.form.get('tenant_id'),
        )
    except ValueError as e:
        flash(str(e), 'danger')
        return redirect(url_for('import_export.import_export_page'))
    if scope_ctx.get('scope') == 'all_tenants' and mode == 'replace_tenant_data':
        flash('Replace mode is blocked for all-tenants scope. Use append mode.', 'danger')
        return redirect(url_for('import_export.import_export_page'))

    try:
        file_bytes = file.read()
        if hasattr(file, 'stream'):
            file.stream.seek(0)
        _archive_artifact_bytes(file_bytes, f"full_raw_import_{file.filename}", kind='imports')
    except Exception as e:
        flash(f'Invalid Excel file: {e}', 'danger')
        return redirect(url_for('import_export.import_export_page'))

    report_name = None
    try:
        report, report_name = _run_full_raw_import_bytes(
            file_bytes=file_bytes,
            scope_ctx=scope_ctx,
            mode=mode,
            source_file_name=file.filename,
        )
        try:
            audit_log(
                current_user,
                'import.full_raw',
                f'mode={mode} inserted={report.get("inserted")} skipped={report.get("skipped")} tables={report.get("tables")}',
            )
        except Exception:
            pass
        msg = (
            f"Full raw import complete ({mode}). Inserted: {report['inserted']}, "
            f"Skipped: {report['skipped']}, Tables: {report['tables']}"
        )
        from blueprints.import_export._pages_transfer_import import _wants_import_json, _import_result_payload
        if _wants_import_json():
            return jsonify(_import_result_payload(True, msg, report, {'report_name': report_name}))
        flash(msg, 'success')
    except Exception as e:
        db.session.rollback()
        from blueprints.import_export._pages_transfer_import import _wants_import_json, _import_result_payload
        if _wants_import_json():
            return jsonify(_import_result_payload(False, f'Full raw import failed: {e}', {})), 400
        flash(f'Full raw import failed: {e}', 'danger')

    return redirect(url_for('import_export.import_export_page', full_raw_import_report=report_name))

