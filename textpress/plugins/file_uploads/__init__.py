# -*- coding: utf-8 -*-
"""
    textpress.plugins.file_uploads
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    Allows to upload files into a web visible folder.

    :copyright: Copyright 2007 by Armin Ronacher
    :license: GNU GPL.
"""
import re
from os import makedirs, remove, sep as pathsep
from os.path import dirname, join, exists
from time import asctime, gmtime, time
from textpress.api import *
from textpress.utils import CSRFProtector, IntelligentRedirect, \
     make_hidden_fields, escape, dump_json
from textpress.models import ROLE_AUTHOR, ROLE_ADMIN
from textpress.views.admin import render_admin_response, flash
from textpress.utils import StreamReporter, ClosingIterator
from textpress.plugins.file_uploads.utils import guess_mimetype, \
     get_upload_folder, list_files, list_images, get_im_version, \
     get_im_path, touch_upload_folder, upload_file, create_thumbnail, \
     file_exists, get_filename


TEMPLATES = join(dirname(__file__), 'templates')
SHARED = join(dirname(__file__), 'shared')


def add_links(req, navigation_bar):
    items =  [
        ('browse', url_for('file_uploads/browse'), _('Browse')),
        ('upload', url_for('file_uploads/upload'), _('Upload')),
        ('thumbnailer', url_for('file_uploads/thumbnailer'),
         _('Create Thumbnails'))
    ]
    if req.user.role >= ROLE_ADMIN:
        items.append(('config', url_for('file_uploads/config'),
                      _('Configure')))

    for pos, (link_id, url, title, children) in enumerate(navigation_bar):
        if link_id == 'posts':
            navigation_bar.insert(pos + 1, ('file_uploads',
                url_for('file_uploads/browse'), _('Uploads'), items))
            break


@require_role(ROLE_AUTHOR)
def do_upload(req):
    csrf_protector = CSRFProtector()
    reporter = StreamReporter()
    add_script(url_for('file_uploads/shared', filename='uploads.js'))
    add_link('stylesheet', url_for('file_uploads/shared', filename='style.css'),
             'text/css')
    add_header_snippet(
        '<script type="text/javascript">'
            '$TRANSPORT_ID = %s'
        '</script>' % escape(dump_json(reporter.transport_id))
    )

    if req.method == 'POST':
        csrf_protector.assert_safe()

        f = req.files['file']
        if not touch_upload_folder():
            flash(_('Could not create upload target folder %s.') %
                  escape(get_upload_folder()), 'error')
            redirect(url_for('file_uploads/upload'))

        filename = req.form.get('filename') or f.filename

        if not f:
            flash(_('No file uploaded.'))
        elif pathsep in filename:
            flash(_('Invalid filename requested.'))
        elif file_exists(filename) and not req.form.get('overwrite'):
            flash(_('A file with the filename %s exists already.') % (
                u'<a href="%s">%s</a>' % (
                    escape(url_for('file_uploads/get_file',
                                   filename=filename)),
                    escape(filename)
                )))
        else:
            upload_file(f, filename)
            flash(_('File %s uploaded successfully.') % (
                  u'<a href="%s">%s</a>' % (
                      escape(url_for('file_uploads/get_file',
                                     filename=filename)),
                      escape(filename))))
        redirect(url_for('file_uploads/upload'))

    return render_admin_response('admin/file_uploads/upload.html',
                                 'file_uploads.upload',
        csrf_protector=csrf_protector,
        reporter=reporter
    )


@require_role(ROLE_AUTHOR)
def do_thumbnailer(req):
    csrf_protector = CSRFProtector()
    redirect = IntelligentRedirect()
    form = {
        'src_image':            '',
        'thumb_width':          '320',
        'thumb_height':         '240',
        'keep_aspect_ratio':    True,
        'thumb_filename':       ''
    }

    im_version = get_im_version()
    if im_version is None:
        path = get_im_path()
        if not path:
            extra = _('If you don\'t have ImageMagick installed system wide '
                      'but in a different folder, you can defined that in '
                      'the <a href="%(config)s">configuration</a>.')
        else:
            extra = _('There is no ImageMagick in the path defined '
                      'installed. (<a href="%(config)s">check the '
                      'configuration</a>)')
        flash((_('Cannot find <a href="%(im)s">ImageMagick</a>.') + ' ' +
               extra) % {
                   'im':        'http://www.imagemagick.org/',
                   'config':    url_for('file_uploads/config')
               }, 'error')

    elif req.method == 'POST':
        errors = []
        csrf_protector.assert_safe()
        form['src_image'] = src_image = req.form.get('src_image')
        if not src_image:
            errors.append(_('You have to specify a source image'))
        try:
            src = file(get_filename(src_image), 'rb')
        except IOError:
            errors.append(_('The image %s does not exist.') %
                          escape(src_image))
        form['thumb_width'] = thumb_width = req.form.get('thumb_width', '')
        form['thumb_height'] = thumb_height = req.form.get('thumb_height', '')
        if not thumb_width:
            errors.append(_('You have to define at least the width of the '
                            'thumbnail.'))
        elif not thumb_width.isdigit() or \
                (thumb_height and not thumb_height.isdigit()):
            errors.append(_('Thumbnail dimensions must be integers.'))
        form['keep_aspect_ratio'] = keep_aspect_ratio = \
                req.form.get('keep_aspect_ratio') == 'yes'
        form['thumb_filename'] = thumb_filename = \
                req.form.get('thumb_filename')
        if not thumb_filename:
            errors.append(_('You have to specify a filename for the '
                            'thumbnail.'))
        elif pathsep in thumb_filename:
            errors.append(_('Invalid filename for thumbnail.'))
        elif file_exists(thumb_filename):
            errors.append(_('An file with this name exists already.'))
        if errors:
            flash(errors[0], 'error')
        else:
            if guess_mimetype(thumb_filename) != 'image/jpeg':
                thumb_filename += '.jpg'
            dst = file(get_filename(thumb_filename), 'wb')
            try:
                dst.write(create_thumbnail(src, thumb_width,
                                           thumb_height or None,
                                           keep_aspect_ratio and 'normal'
                                           or 'force', 90, True))
            finally:
                dst.close()
            flash(_('Thumbnail %s was created successfully.') % (
                  u'<a href="%s">%s</a>' % (
                      escape(url_for('file_uploads/get_file',
                                     filename=thumb_filename)),
                      escape(thumb_filename))))
            redirect('file_uploads/browse')

    return render_admin_response('admin/file_uploads/thumbnailer.html',
                                 'file_uploads.thumbnailer',
        im_version=im_version,
        images=list_images(),
        form=form,
        hidden_form_data=make_hidden_fields(csrf_protector, redirect)
    )


@require_role(ROLE_AUTHOR)
def do_browse(req):
    return render_admin_response('admin/file_uploads/browse.html',
                                 'file_uploads.browse',
        files=list_files()
    )


@require_role(ROLE_ADMIN)
def do_config(req):
    csrf_protector = CSRFProtector()
    form = {
        'upload_dest':  req.app.cfg['file_uploads/upload_folder'],
        'im_path':      req.app.cfg['file_uploads/im_path'],
        'mimetypes':    u'\n'.join(req.app.cfg['file_uploads/mimetypes'].
                                   split(';'))
    }
    if req.method == 'POST':
        csrf_protector.assert_safe()
        upload_dest = form['upload_dest'] = req.form.get('upload_dest', '')
        if upload_dest != req.app.cfg['file_uploads/upload_folder']:
            req.app.cfg['file_uploads/upload_folder'] = upload_dest
            flash(_('Upload folder changed successfully.'))
        im_path = form['im_path'] = req.form.get('im_path', '')
        if im_path != req.app.cfg['file_uploads/im_path']:
            req.app.cfg['file_uploads/im_path'] = im_path
            if im_path:
                flash(_('Changed path to ImageMagick'))
            else:
                flash(_('ImageMagick is searched on the system path now.'))
        mimetypes = form['mimetypes'] = req.form.get('mimetypes', '')
        mimetypes = ';'.join(mimetypes.splitlines())
        if mimetypes != req.app.cfg['file_uploads/mimetypes']:
            req.app.cfg['file_uploads/mimetypes'] = mimetypes
            if req.app in _mimetype_cache:
                del _mimetype_cache[req.app][:]
            flash(_('Upload mimetype mapping altered successfully.'))
        redirect(url_for('file_uploads/config'))

    return render_admin_response('admin/file_uploads/config.html',
                                 'file_uploads.config',
        im_version=get_im_version(),
        form=form,
        csrf_protector=csrf_protector
    )


def do_get_file(req, filename):
    filename = get_filename(filename)
    if not exists(filename):
        abort(404)
    guessed_type = guess_mimetype(filename)
    fp = file(filename, 'rb')
    def stream():
        while True:
            chunk = fp.read(1024 * 512)
            if not chunk:
                break
            yield chunk
    resp = Response(ClosingIterator(stream(), fp.close),
                    mimetype=guessed_type or 'text/plain')
    resp.headers['Cache-Control'] = 'public'
    resp.headers['Expires'] = asctime(gmtime(time() + 3600))
    return resp


@require_role(ROLE_AUTHOR)
def do_delete(req, filename):
    fs_filename = get_filename(filename)
    if not exists(fs_filename):
        abort(404)

    csrf_protector = CSRFProtector()
    redirect = IntelligentRedirect()

    if req.method == 'POST':
        csrf_protector.assert_safe()
        if req.form.get('confirm'):
            try:
                remove(fs_filename)
            except (OSError, IOError):
                flash(_('Could not delete file %s.') %
                      escape(filename), 'error')
            else:
                flash(_('File %s deleted successfully.') %
                      escape(filename), 'remove')
        redirect('file_uploads/browse')

    return render_admin_response('admin/file_uploads/delete.html',
                                 'file_uploads.browse',
        hidden_form_data=make_hidden_fields(csrf_protector, redirect),
        filename=filename
    )


def setup(app, plugin):
    app.add_config_var('file_uploads/upload_folder', unicode, 'uploads')
    app.add_config_var('file_uploads/mimetypes', unicode,
                       '*.plugin:application/x-textpress-plugin')
    app.add_config_var('file_uploads/im_path', unicode, '')
    app.connect_event('modify-admin-navigation-bar', add_links)
    app.add_url_rule('/admin/uploads/', endpoint='file_uploads/browse'),
    app.add_url_rule('/admin/uploads/new', endpoint='file_uploads/upload')
    app.add_url_rule('/admin/uploads/thumbnailer',
                     endpoint='file_uploads/thumbnailer')
    app.add_url_rule('/admin/uploads/config', endpoint='file_uploads/config')
    app.add_url_rule('/_uploads/<filename>', endpoint='file_uploads/get_file')
    app.add_url_rule('/_uploads/<filename>/delete',
                     endpoint='file_uploads/delete')
    app.add_view('file_uploads/browse', do_browse)
    app.add_view('file_uploads/upload', do_upload)
    app.add_view('file_uploads/thumbnailer', do_thumbnailer)
    app.add_view('file_uploads/config', do_config)
    app.add_view('file_uploads/get_file', do_get_file)
    app.add_view('file_uploads/delete', do_delete)
    app.add_template_searchpath(TEMPLATES)
    app.add_shared_exports('file_uploads', SHARED)
