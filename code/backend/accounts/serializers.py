from rest_framework import serializers
from django.contrib.auth import get_user_model, password_validation
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer


User = get_user_model()


def get_legacy_role(user):
    if getattr(user, 'is_superuser', False) or getattr(user, 'is_staff', False):
        return 'admin'
    return 'citizen'


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = (
            'id',
            'username',
            'email',
            'first_name',
            'last_name',
            'is_staff',
            'is_active',
        )


class UserRegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)
    email = serializers.EmailField(required=True)

    class Meta:
        model = User
        fields = ('username', 'email', 'password')

    def validate_email(self, value):
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError('A user with this email already exists.')
        return value

    def validate(self, attrs):
        candidate = User(username=attrs.get("username", ""), email=attrs.get("email", ""))
        try:
            password_validation.validate_password(attrs.get("password", ""), user=candidate)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"password": list(exc.messages)}) from None
        return attrs

    def create(self, validated_data):
        return User.objects.create_user(
            username=validated_data['username'],
            email=validated_data['email'],
            password=validated_data['password'],
        )


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token['username'] = user.username
        token['email'] = user.email
        token['role'] = get_legacy_role(user)
        return token

    def validate(self, attrs):
        # The RoutIQ UI accepts either username or email in the same field.
        # Normalize the submitted identity before SimpleJWT calls authenticate().
        identity = attrs.get(self.username_field)
        if isinstance(identity, str):
            identity = identity.strip()
            attrs[self.username_field] = identity
            if '@' in identity:
                user_by_email = User.objects.filter(email__iexact=identity).order_by('id').first()
                if user_by_email is not None:
                    attrs[self.username_field] = user_by_email.get_username()

        data = super().validate(attrs)
        user = self.user
        data['user'] = UserSerializer(user).data
        data['role'] = get_legacy_role(user)
        return data
