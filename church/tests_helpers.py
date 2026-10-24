from django.contrib.auth import get_user_model

from church.models import Branch

User = get_user_model()


def make_user(email, role=User.Role.MEMBER, password="pass12345!Xy", **extra):
    return User.objects.create_user(username=email, email=email, password=password, role=role,
                                    first_name=extra.pop("first_name", email.split("@")[0].title()), **extra)


def make_branch(name, *admins, **extra):
    b = Branch.objects.create(name=name, **extra)
    b.admins.set(admins)
    return b
