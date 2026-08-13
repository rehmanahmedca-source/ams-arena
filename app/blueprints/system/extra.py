"""extra — split from system.py."""
from ._common import *  # noqa

@bp.route('/ams_assistant')
@login_required
def ams_assistant_page():
    return render_template('ams_assistant.html')


