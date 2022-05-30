from importlib.resources import path
# from lib2to3.pgen2 import token
from xml import dom
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils.decorators import method_decorator
from django.views.generic import CreateView, ListView, UpdateView , TemplateView
from django.utils import timezone
from ..forms import StudentInterestsForm, StudentSignUpForm, TakeQuizForm
from ..models import Quiz, Student, TakenQuiz, User, Assignment, AssignmentSubmission
from django.views import View
from ..forms import StudentSignUpForm
from django.core.mail import EmailMessage
from django.utils.encoding import force_bytes, force_text, DjangoUnicodeDecodeError
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.contrib.sites.shortcuts import get_current_site
from django.urls import reverse
from ..utils import token_generator
from django.shortcuts import render
from django import forms
from django.contrib.sites.models import Site
import time


class StudentSignUpView(CreateView):
    model = User
    form_class = StudentSignUpForm
    template_name = 'registration/signup_student_form.html'

    def get_context_data(self, **kwargs):
        kwargs['user_type'] = 'student'
        return super().get_context_data(**kwargs)

    def form_valid(self, form, backend='django.contrib.auth.backends.ModelBackend'):
        user = form.save()
        userEmail = user.email
        print(user.email)
        user.is_active = False
        user.save()

        email_subject = "Activate your account"

        # path to view
        # - getting domain we are on
        # -relative url to verification
        # -encode uid
        # -token

        uidb64 = urlsafe_base64_encode(force_bytes(user.pk))
        current_site = Site.objects.get_current()
        # domain=current_site.domain
        domain = 'localhost:8000'

        # domain=get_current_site(self.request).domain
        print(domain)
        link = reverse('activate1', kwargs={'uidb64': uidb64, 'token': token_generator.make_token(user)})
        print(link)
        activate_url = 'http://' + domain + link
        email_body = 'Hi ' + user.username + ' Please use this link to verify your account\n' + activate_url

        email = EmailMessage(
            email_subject,
            email_body,
            'noreply@classDeck.com',
            [userEmail],

        )

        email.send(fail_silently=False)
        messages.success(self.request, "Check your mail to activate your account")
        return render(self.request, 'registration/login.html')
        # login(self.request, user, backend='django.contrib.auth.backends.ModelBackend')
        # return redirect('students:quiz_list')


@method_decorator([login_required], name='dispatch')
class HomeView(TemplateView):
    template_name = 'classroom/students/student_home.html'


@method_decorator([login_required], name='dispatch')
class StudentInterestsView(UpdateView):
    model = Student
    form_class = StudentInterestsForm
    template_name = 'classroom/students/interests_form.html'
    success_url = reverse_lazy('students:quiz_list')

    def get_object(self):
        return self.request.user.student

    def form_valid(self, form):
        messages.success(self.request, 'Interests updated with success!')
        return super().form_valid(form)


@method_decorator([login_required], name='dispatch')
class QuizListView(ListView):
    model = Quiz
    ordering = ('name',)
    context_object_name = 'quizzes'
    template_name = 'classroom/students/quiz_list.html'

    def get_queryset(self):
        student = self.request.user.student
        student_interests = student.interests.values_list('pk', flat=True)
        taken_quizzes = student.quizzes.values_list('pk', flat=True)
        queryset = Quiz.objects.filter(subject__in=student_interests) \
            .exclude(pk__in=taken_quizzes) \
            .annotate(questions_count=Count('questions')) \
            .filter(questions_count__gt=0)
        return queryset

@method_decorator([login_required], name='dispatch')
class AssignmentListView(View):
    def get(self, request):
        student = Student.objects.get(user=self.request.user)
        data = []
        assignments = Assignment.objects.all()
        for i in assignments:
            assignment = {}
            assignment['name'] = i.name
            assignment['subject'] = i.subject
            assignment['last_date'] = i.last_date
            assignment['assignment_id'] = i.id
            if len(AssignmentSubmission.objects.filter(assignment=i,student=student))>0:
                assignment['submitted'] = True
                assignment['response_id'] = AssignmentSubmission.objects.filter(assignment=i,student=student)[0].id
            else :
                assignment['submitted'] = False
            data.append(assignment)
        return render(request, 'classroom/students/assignment_list.html',{'assignments':data})


@method_decorator([login_required], name='dispatch')
class CreateResponseView(View):
    def get(self,request,pk):
        assignment = Assignment.objects.get(id=pk)
        return render(request,'classroom/students/create_response.html',{'assignment':assignment})

    def post(self,request,pk):
        file = request.FILES['file']
        today = timezone.now()
        assignment = Assignment.objects.get(id=pk)
        late_submission = False
        if today>assignment.last_date:
            late_submission = True
        new = AssignmentSubmission(assignment=assignment,
                            file=file,
                            student=Student.objects.get(user=self.request.user),
                            late_submission=late_submission)
        new.save()
        messages.success(request, 'Your response was saved successfuly !')
        return redirect('students:assignment_list')


@method_decorator([login_required], name='dispatch')
class ResponseView(View):
    def get(self,request,pk):
        response = AssignmentSubmission.objects.get(id=pk)
        return render(request, 'classroom/students/view_response.html',{'response':response})


@method_decorator([login_required], name='dispatch')
class TakenQuizListView(ListView):
    model = TakenQuiz
    context_object_name = 'taken_quizzes'
    template_name = 'classroom/students/taken_quiz_list.html'

    def get_queryset(self):
        queryset = self.request.user.student.taken_quizzes \
            .select_related('quiz', 'quiz__subject') \
            .order_by('quiz__name')
        return queryset


@login_required
def take_quiz(request, pk, qno):
    quiz = get_object_or_404(Quiz, pk=pk)
    student = request.user.student

    if student.quizzes.filter(pk=pk).exists():
        return render(request, 'students/taken_quiz.html')

    total_questions = quiz.questions.count()
    quiz_questions = quiz.questions.all()
    dur = quiz.duration 
    quiz_duration = dur.hour*60*60*1000 + dur.minute*60*1000 + dur.second*1000
    unanswered_questions = student.get_unanswered_questions(quiz)
    unanswered_question_ids = [question.id for question in unanswered_questions]
    total_unanswered_questions = unanswered_questions.count()
    progress = 100 - round(((total_unanswered_questions - 1) / total_questions) * 100)
    question = quiz_questions[qno - 1]
    student_answers = student.quiz_answers.filter(answer__question__quiz=quiz)
    if request.method == 'POST':
        form = TakeQuizForm(question=question, data=request.POST)
        if qno not in unanswered_question_ids:
            for i in student_answers:
                if i.answer.question.id == qno:
                    form = TakeQuizForm(question=question, instance=i, data=request.POST)
                    break
        if form.is_valid():
            with transaction.atomic():
                student_answer = form.save(commit=False)
                student_answer.student = student
                student_answer.save()
                if student.get_unanswered_questions(quiz).exists():
                    '''student.get_unanswered_questions(quiz).first().id'''
                    return redirect('students:take_quiz', pk, qno)
                else:
                    correct_answers = student.quiz_answers.filter(answer__question__quiz=quiz,
                                                                  answer__is_correct=True).count()
                    score = round((correct_answers / total_questions) * 100.0, 2)
                    TakenQuiz.objects.create(student=student, quiz=quiz, score=score)
                    if score < 50.0:
                        messages.warning(request, 'Better luck next time! Your score for the quiz %s was %s.' % (
                            quiz.name, score))
                    else:
                        messages.success(request,
                                         'Congratulations! You completed the quiz %s with success! You scored %s points.' % (
                                             quiz.name, score))
                    return redirect('students:quiz_list')
    else:
        form = TakeQuizForm(question=question)
        if qno not in unanswered_question_ids:
            for i in student_answers:
                if i.answer.question.id == qno:
                    form = TakeQuizForm(question=question, instance=i)
                    break
    return render(request, 'classroom/students/take_quiz_form.html', {
        'quiz': quiz,
        'question': question,
        'duration': quiz_duration,
        'form': form,
        'progress': progress,
        'total_questions': [{"id": i + 1, "status": i + 1 in unanswered_question_ids} for i in range(total_questions)],
        'prev': qno - 1 if qno - 1 > 0 else False,
        'next': qno + 1 if qno + 1 <= total_questions else False,
    })


class VerificationView(TemplateView):
    def get(self, request, uidb64, token):
        print('IN')

        id = force_text(urlsafe_base64_decode(uidb64))
        user = User.objects.get(pk=id)

        user.is_active = True
        user.save()
        messages.success(request, "Account activated successfully")
        login(self.request, user, backend='django.contrib.auth.backends.ModelBackend')

        return render(self.request, 'classroom/students/student_home.html')
