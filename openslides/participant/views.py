# -*- coding: utf-8 -*-

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.views import login as django_login
from django.core.urlresolvers import reverse
from django.shortcuts import redirect
from django.utils.translation import ugettext as _
from django.utils.translation import activate, ugettext_lazy

from openslides.config.api import config
from openslides.utils.template import Tab
from openslides.utils.utils import (delete_default_permissions, html_strong,
                                    template)
from openslides.utils.views import (CreateView, DeleteView, DetailView,
                                    FormView, ListView, PDFView,
                                    PermissionMixin, QuestionView,
                                    RedirectView, SingleObjectMixin, UpdateView)

from .api import gen_password, gen_username, import_users
from .forms import (GroupForm, UserCreateForm, UserImportForm, UsersettingsForm,
                    UserUpdateForm)
from .models import get_protected_perm, Group, User
from .pdf import participants_to_pdf, participants_passwords_to_pdf


class UserOverview(ListView):
    """
    Show all participants (users).
    """
    permission_required = 'participant.can_see_participant'
    template_name = 'participant/overview.html'
    context_object_name = 'users'

    def get_queryset(self):
        query = User.objects
        if config['participant_sort_users_by_first_name']:
            query = query.order_by('first_name')
        else:
            query = query.order_by('last_name')
        return query.all()

    def get_context_data(self, **kwargs):
        context = super(UserOverview, self).get_context_data(**kwargs)
        all_users = User.objects.count()
        # context vars
        context.update({
            'allusers': all_users,
            'request_user': self.request.user})
        return context


class UserDetailView(DetailView, PermissionMixin):
    """
    Classed based view to show a specific user in the interface.
    """
    permission_required = 'participant.can_see_participant'
    model = User
    template_name = 'participant/user_detail.html'
    context_object_name = 'shown_user'


class UserCreateView(CreateView):
    """
    Create a new participant.
    """
    permission_required = 'participant.can_manage_participant'
    template_name = 'participant/edit.html'
    model = User
    context_object_name = 'edit_user'
    form_class = UserCreateForm
    success_url_name = 'user_overview'
    url_name_args = []

    def manipulate_object(self, form):
        self.object.username = gen_username(
            form.cleaned_data['first_name'], form.cleaned_data['last_name'])
        if not self.object.default_password:
            self.object.default_password = gen_password()
        self.object.set_password(self.object.default_password)

    def post_save(self, form):
        super(UserCreateView, self).post_save(form)
        # TODO: find a better solution that makes the following lines obsolete
        # Background: motion.models.use_post_save adds already the registerd group
        # to new user but super(..).post_save(form) removes it and sets only the
        # groups selected in the form (without 'registered')
        # workaround: add registered group again manually
        from openslides.participant.api import get_registered_group  # TODO: Test, if global import is possible
        registered = get_registered_group()
        self.object.groups.add(registered)


class UserUpdateView(UpdateView):
    """
    Update an existing participant.
    """
    permission_required = 'participant.can_manage_participant'
    template_name = 'participant/edit.html'
    model = User
    context_object_name = 'edit_user'
    form_class = UserUpdateForm
    success_url_name = 'user_overview'
    url_name_args = []

    def get_form_kwargs(self, *args, **kwargs):
        form_kwargs = super(UserUpdateView, self).get_form_kwargs(*args, **kwargs)
        form_kwargs.update({'request': self.request})
        return form_kwargs

    def manipulate_object(self, form):
        self.object.username = form.cleaned_data['user_name']

    def post_save(self, form):
        super(UserUpdateView, self).post_save(form)
        # TODO: find a better solution that makes the following lines obsolete
        # Background: motion.models.use_post_save adds already the registerd group
        # to new user but super(..).post_save(form) removes it and sets only the
        # groups selected in the form (without 'registered')
        # workaround: add registered group again manually
        from openslides.participant.api import get_registered_group  # TODO: Test, if global import is possible
        registered = get_registered_group()
        self.object.groups.add(registered)


class UserDeleteView(DeleteView):
    """
    Delete an participant.
    """
    permission_required = 'participant.can_manage_participant'
    model = User
    success_url_name = 'user_overview'
    url_name_args = []

    def pre_redirect(self, request, *args, **kwargs):
        if self.object == self.request.user:
            messages.error(request, _("You can not delete yourself."))
        else:
            super(UserDeleteView, self).pre_redirect(request, *args, **kwargs)

    def pre_post_redirect(self, request, *args, **kwargs):
        if self.object == self.request.user:
            messages.error(self.request, _("You can not delete yourself."))
        else:
            super(UserDeleteView, self).pre_post_redirect(request, *args, **kwargs)


class SetUserStatusView(RedirectView, SingleObjectMixin):
    """
    Activate or deactivate an user.
    """
    permission_required = 'participant.can_manage_participant'
    allow_ajax = True
    url_name = 'user_overview'
    model = User

    def pre_redirect(self, request, *args, **kwargs):
        self.object = self.get_object()
        action = kwargs['action']
        if action == 'activate':
            self.object.is_active = True
        elif action == 'deactivate':
            if self.object.user == self.request.user:
                messages.error(request, _("You can not deactivate yourself."))
                return
            self.object.is_active = False
        elif action == 'toggle':
            self.object.is_active = not self.object.is_active
        self.object.save()
        return super(SetUserStatusView, self).pre_redirect(request, *args, **kwargs)

    def get_ajax_context(self, **kwargs):
        context = super(SetUserStatusView, self).get_ajax_context(**kwargs)
        context['active'] = self.object.is_active
        return context


class ParticipantsListPDF(PDFView):
    """
    Generate the userliste as PDF.
    """
    permission_required = 'participant.can_see_participant'
    filename = ugettext_lazy("Participant-list")
    document_title = ugettext_lazy('List of Participants')

    def append_to_pdf(self, pdf):
        """
        Append PDF objects.
        """
        participants_to_pdf(pdf)


class ParticipantsPasswordsPDF(PDFView):
    """
    Generate the access data welcome paper for all participants as PDF.
    """
    permission_required = 'participant.can_manage_participant'
    filename = ugettext_lazy("Participant-access-data")
    top_space = 0

    def build_document(self, pdf_document, story):
        pdf_document.build(story)

    def append_to_pdf(self, pdf):
        """
        Append PDF objects.
        """
        participants_passwords_to_pdf(pdf)


class UserImportView(FormView):
    """
    Import Users via csv.
    """
    permission_required = 'participant.can_manage_participant'
    template_name = 'participant/import.html'
    form_class = UserImportForm
    success_url_name = 'user_overview'

    def form_valid(self, form):
        # check for valid encoding (will raise UnicodeDecodeError if not)
        success, error_messages = import_users(self.request.FILES['csvfile'])
        for message in error_messages:
            messages.error(self.request, message)
        if success:
            messages.success(
                self.request,
                _('%d new participants were successfully imported.') % success)
        return super(UserImportView, self).form_valid(form)


class ResetPasswordView(SingleObjectMixin, QuestionView):
    """
    Set the Passwort for a user to his default password.
    """
    permission_required = 'participant.can_manage_participant'
    model = User
    allow_ajax = True
    question_message = ugettext_lazy('Do you really want to reset the password?')

    def get(self, request, *args, **kwargs):
        self.object = self.get_object()
        return super(ResetPasswordView, self).get(request, *args, **kwargs)

    def get_redirect_url(self, **kwargs):
        return reverse('user_edit', args=[self.object.id])

    def on_clicked_yes(self):
        self.object.reset_password()

    def get_final_message(self):
        return _('The Password for %s was successfully reset.') % html_strong(self.object)


class GroupOverview(ListView):
    """
    Overview over all groups.
    """
    permission_required = 'participant.can_manage_participant'
    template_name = 'participant/group_overview.html'
    context_object_name = 'groups'
    model = Group


class GroupDetailView(DetailView, PermissionMixin):
    """
    Classed based view to show a specific group in the interface.
    """
    permission_required = 'participant.can_manage_participant'
    model = Group
    template_name = 'participant/group_detail.html'
    context_object_name = 'group'

    def get_context_data(self, *args, **kwargs):
        context = super(GroupDetailView, self).get_context_data(*args, **kwargs)
        query = User.objects
        if config['participant_sort_users_by_first_name']:
            query = query.order_by('first_name')
        else:
            query = query.order_by('last_name')
        context['group_members'] = query.filter(django_user__groups__in=[context['group']])
        return context


class GroupCreateView(CreateView):
    """
    Create a new group.
    """
    permission_required = 'participant.can_manage_participant'
    template_name = 'participant/group_edit.html'
    context_object_name = 'group'
    model = Group
    form_class = GroupForm
    success_url_name = 'user_group_overview'
    url_name_args = []

    def get(self, request, *args, **kwargs):
        delete_default_permissions()
        return super(GroupCreateView, self).get(request, *args, **kwargs)


class GroupUpdateView(UpdateView):
    """
    Update an existing group.
    """
    permission_required = 'participant.can_manage_participant'
    template_name = 'participant/group_edit.html'
    model = Group
    context_object_name = 'group'
    form_class = GroupForm
    success_url_name = 'user_group_overview'
    url_name_args = []

    def get(self, request, *args, **kwargs):
        delete_default_permissions()
        return super(GroupUpdateView, self).get(request, *args, **kwargs)

    def get_form_kwargs(self, *args, **kwargs):
        form_kwargs = super(GroupUpdateView, self).get_form_kwargs(*args, **kwargs)
        form_kwargs.update({'request': self.request})
        return form_kwargs


class GroupDeleteView(DeleteView):
    """
    Delete a group.
    """
    permission_required = 'participant.can_manage_participant'
    model = Group
    success_url_name = 'user_group_overview'
    url_name_args = []

    def pre_redirect(self, request, *args, **kwargs):
        if not self.is_protected_from_deleting():
            super(GroupDeleteView, self).pre_redirect(request, *args, **kwargs)

    def pre_post_redirect(self, request, *args, **kwargs):
        if not self.is_protected_from_deleting():
            super(GroupDeleteView, self).pre_post_redirect(request, *args, **kwargs)

    def is_protected_from_deleting(self):
        """
        Checks whether the group is protected.
        """
        if self.object.pk in [1, 2]:
            messages.error(self.request, _('You can not delete this group.'))
            return True
        if (not self.request.user.is_superuser and
            get_protected_perm() in self.object.permissions.all() and
            not Group.objects.exclude(pk=self.object.pk).filter(
                permissions__in=[get_protected_perm()],
                user__pk=self.request.user.pk).exists()):
            messages.error(
                self.request,
                _('You can not delete the last group containing the permission '
                  'to manage participants you are in.'))
            return True
        return False


def login(request):
    extra_content = {}
    try:
        admin = User.objects.get(pk=1)
        if admin.check_password(admin.default_password):
            user_data = {
                'user': html_strong(admin.username),
                'password': html_strong(admin.default_password)}

            extra_content['first_time_message'] = _(
                "Installation was successfully! Use %(user)s "
                "(password: %(password)s) for first login.<br>"
                "<strong>Important:</strong> Please change the password after "
                "first login! Otherwise this message still appears for "
                "everyone  and could be a security risk.") % user_data

            extra_content['next'] = reverse('password_change')
    except User.DoesNotExist:
        pass
    return django_login(request, template_name='participant/login.html', extra_context=extra_content)


@login_required
@template('participant/settings.html')
def user_settings(request):
    """
    Edit own user account.
    """
    if request.method == 'POST':
        form_user = UsersettingsForm(request.POST, instance=request.user)
        if form_user.is_valid():
            user = form_user.save(commit=False)
            user.username = form_user.cleaned_data['user_name']
            user.save()
            language = request.LANGUAGE_CODE = \
                request.session['django_language'] = form_user.cleaned_data['language']
            activate(language)
            messages.success(request, _('User settings successfully saved.'))
        else:
            messages.error(request, _('Please check the form for errors.'))
    else:
        language = request.session.get('django_language', request.LANGUAGE_CODE)
        form_user = UsersettingsForm(instance=request.user, initial={'language': language})

    return {
        'form': form_user,
        'edituser': request.user,
    }


@login_required
@template('participant/password_change.html')
def user_settings_password(request):
    """
    Edit own password.
    """
    if request.method == 'POST':
        form = PasswordChangeForm(request.user, request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, _('Password successfully changed.'))
            return redirect(reverse('dashboard'))
        else:
            messages.error(request, _('Please check the form for errors.'))
    else:
        form = PasswordChangeForm(user=request.user)

    return {
        'form': form,
    }


def register_tab(request):
    """
    Registers the participant tab.
    """
    selected = request.path.startswith('/participant/')
    return Tab(
        title=_('Participants'),
        app='participant',
        url=reverse('user_overview'),
        permission=(
            request.user.has_perm('participant.can_see_participant') or
            request.user.has_perm('participant.can_manage_participant')),
        selected=selected)
