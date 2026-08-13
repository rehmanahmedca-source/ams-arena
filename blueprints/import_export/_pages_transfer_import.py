"""pages — split from import_export.py."""
from ._common import *  # noqa

def _wants_import_json():
    if (request.args.get('format') or request.form.get('format') or '').lower() == 'json':
        return True
    if request.headers.get('X-Requested-With') == 'fetch':
        return True
    accept = (request.headers.get('Accept') or '').lower()
    return 'application/json' in accept


def _import_result_payload(ok, headline, report, extra=None):
    payload = {
        'ok': bool(ok),
        'headline': headline,
        'inserted': (report or {}).get('inserted') or (report or {}).get('imported') or 0,
        'updated': (report or {}).get('updated') or 0,
        'skipped': (report or {}).get('skipped') or 0,
        'errors': (report or {}).get('errors') or 0,
        'tables': (report or {}).get('tables'),
        'table_results': (report or {}).get('table_results') or [],
        'users': (report or {}).get('users') or [],
    }
    if extra:
        payload.update(extra)
    return payload


@import_export_bp.route('/transfer/import', methods=['POST'])
@login_required
def transfer_import():
    # ===== PANDAS DEPENDENCY CHECK =====
    if not _validate_pandas_installed():
        flash('CRITICAL: pandas library is not installed. Run: pip install pandas>=2.3.3', 'danger')
        return redirect(url_for('import_export.import_export_page'))
    # ===== END DEPENDENCY CHECK =====
    
    file = request.files.get('file')
    if not file:
        flash('Please upload an Excel file.', 'danger')
        return redirect(url_for('import_export.import_export_page'))

    try:
        scope_ctx = _resolve_scope_context(
            scope_raw=request.form.get('scope'),
            tenant_id_raw=request.form.get('tenant_id'),
        )
    except ValueError as e:
        flash(str(e), 'danger')
        return redirect(url_for('import_export.import_export_page'))

    sections = [str(x).strip().lower() for x in request.form.getlist('sections') if str(x).strip()]
    if not sections:
        sections = ['all_business']

    try:
        file_bytes = file.read()
        if hasattr(file, 'stream'):
            file.stream.seek(0)
        _archive_artifact_bytes(file_bytes, f"transfer_import_{file.filename}", kind='imports')
    except Exception as e:
        flash(f'Invalid file: {e}', 'danger')
        return redirect(url_for('import_export.import_export_page'))

    detected_kind = _detect_transfer_workbook_kind(file_bytes)
    if detected_kind == 'literal_all' and 'literal_all' not in sections:
        sections = ['literal_all']
        flash('Detected Literal Full Raw workbook. Switched import mode automatically.', 'info')
    elif detected_kind == 'all_business' and 'literal_all' in sections and 'all_business' not in sections:
        sections = ['all_business']
        flash('Detected Master Backup workbook. Switched import mode automatically.', 'info')

    if 'literal_all' in sections:
        if not _full_raw_import_enabled():
            flash('Literal Full Import is disabled by safety toggle.', 'warning')
            return redirect(url_for('import_export.import_export_page'))
        mode = (request.form.get('mode') or 'append').strip().lower()
        if mode not in ['append', 'replace_tenant_data']:
            mode = 'append'
        if scope_ctx.get('scope') == 'all_tenants' and mode == 'replace_tenant_data':
            flash('Replace mode is blocked for all-tenants scope. Use append mode.', 'danger')
            return redirect(url_for('import_export.import_export_page'))
        try:
            report, report_name = _run_full_raw_import_bytes(
                file_bytes=file_bytes,
                scope_ctx=scope_ctx,
                mode=mode,
                source_file_name=file.filename,
            )
            flash(
                f"Literal full import complete ({mode}). Inserted: {report['inserted']}, "
                f"Skipped: {report['skipped']}, Tables: {report['tables']}",
                'success'
            )
            return redirect(url_for('import_export.import_export_page', full_raw_import_report=report_name))
        except Exception as e:
            db.session.rollback()
            flash(f'Literal full import failed: {e}', 'danger')
            return redirect(url_for('import_export.import_export_page'))

    if getattr(current_user, 'role', None) == 'root' and scope_ctx.get('scope') == 'all_tenants':
        flash('Root all-tenant master import is blocked. Use Literal Full Import for all-tenant restore.', 'danger')
        return redirect(url_for('import_export.import_export_page'))

    try:
        run_bytes = file_bytes
        if 'all_business' not in sections:
            sheet_names = _selected_master_sheets(sections)
            if not sheet_names:
                flash('Select at least one section for import.', 'warning')
                return redirect(url_for('import_export.import_export_page'))
            run_bytes = _filter_excel_bytes_to_sheets(file_bytes, sheet_names)

        _set_import_actor_context(
            username=getattr(current_user, 'username', None),
            tenant_id=scope_ctx.get('target_tenant_id'),
            role=getattr(current_user, 'role', None),
        )
        g.enforce_tenant = (scope_ctx.get('scope') == 'tenant' and scope_ctx.get('target_tenant_id') is not None)
        g.tenant_id = scope_ctx.get('target_tenant_id')
        report = _run_master_import_bytes(
            file_bytes=run_bytes,
            actor_username=getattr(current_user, 'username', None),
            progress_cb=None,
        )
        msg = (
            f"Import complete. Imported: {report.get('imported', 0)}, "
            f"Updated: {report.get('updated', 0)}, Skipped: {report.get('skipped', 0)}."
        )
        if _wants_import_json():
            return jsonify(_import_result_payload(True, msg, report))
        flash(msg, 'success')
    except Exception as e:
        db.session.rollback()
        if _wants_import_json():
            return jsonify(_import_result_payload(False, f'Import failed: {e}', {})), 400
        flash(f'Import failed: {e}', 'danger')
    finally:
        _clear_import_actor_context()
    return redirect(url_for('import_export.import_export_page'))

