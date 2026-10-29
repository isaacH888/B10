"""Security contracts for the deployable template; no AWS credentials needed."""

import json
import re
from pathlib import Path

TEMPLATE = json.loads(
    (Path(__file__).resolve().parents[2] / "infra/cognito-authentication.json").read_text()
)
RESOURCES = TEMPLATE["Resources"]


def props(name):
    return RESOURCES[name]["Properties"]


def test_admin_pool_requires_password_and_totp_with_private_recovery():
    admin = props("AdminPool")
    assert admin["UserPoolTier"] == "PLUS"
    assert admin["AdminCreateUserConfig"]["AllowAdminCreateUserOnly"] is True
    assert admin["MfaConfiguration"] == "ON"
    assert admin["EnabledMfas"] == ["SOFTWARE_TOKEN_MFA"]
    assert admin["Policies"]["SignInPolicy"]["AllowedFirstAuthFactors"] == ["PASSWORD"]
    assert admin["AccountRecoverySetting"]["RecoveryMechanisms"] == [
        {"Name": "admin_only", "Priority": 1}
    ]
    assert "DeviceConfiguration" not in admin
    assert admin["Policies"]["PasswordPolicy"]["MinimumLength"] >= 16


def test_customer_supports_google_and_password_while_admin_is_native_only():
    assert props("CustomerPool")["UserPoolTier"] == "ESSENTIALS"
    assert props("CustomerPool")["AdminCreateUserConfig"]["AllowAdminCreateUserOnly"] is False
    assert props("GoogleProvider")["UserPoolId"] == {"Ref": "CustomerPool"}
    assert "AdminGoogleProvider" not in RESOURCES
    assert "DependsOn" not in RESOURCES["AdminClient"]
    assert RESOURCES["CustomerClient"]["DependsOn"] == "GoogleProvider"
    providers = [
        resource["Properties"]
        for resource in RESOURCES.values()
        if resource["Type"] == "AWS::Cognito::UserPoolIdentityProvider"
    ]
    assert len(providers) == 1 and providers[0]["UserPoolId"] == {"Ref": "CustomerPool"}
    assert props("GoogleProvider")["AttributeMapping"] == {
        "email": "email",
        "email_verified": "email_verified",
        "name": "name",
    }
    assert props("AdminClient")["SupportedIdentityProviders"] == ["COGNITO"]
    assert props("CustomerClient")["SupportedIdentityProviders"] == ["COGNITO", "Google"]
    assert "aws.cognito.signin.user.admin" in props("CustomerClient")["AllowedOAuthScopes"]
    assert "aws.cognito.signin.user.admin" in props("AdminClient")["AllowedOAuthScopes"]
    assert props("CustomerClient")["WriteAttributes"] == ["email", "name"]
    assert props("AdminClient")["WriteAttributes"] == ["email"]
    assert props("AdminClient")["ReadAttributes"] == ["email", "email_verified", "name"]
    assert "identities" not in props("AdminClient")["WriteAttributes"]


def test_clients_use_code_and_rotated_short_tokens():
    for name, minutes, hours in [("AdminClient", 5, 8), ("CustomerClient", 15, 168)]:
        client = props(name)
        assert client["GenerateSecret"] is True
        assert client["AllowedOAuthFlows"] == ["code"]
        assert client["EnableTokenRevocation"] is True
        assert client["PreventUserExistenceErrors"] == "ENABLED"
        assert client["RefreshTokenRotation"] == {
            "Feature": "ENABLED",
            "RetryGracePeriodSeconds": 10,
        }
        assert "ALLOW_REFRESH_TOKEN_AUTH" not in client["ExplicitAuthFlows"]
        assert client["AccessTokenValidity"] == client["IdTokenValidity"] == minutes
        assert client["RefreshTokenValidity"] == hours
        assert client["TokenValidityUnits"] == {
            "AccessToken": "minutes",
            "IdToken": "minutes",
            "RefreshToken": "hours",
        }


def test_native_admin_challenges_use_public_user_auth_without_iam_or_device_bypass():
    client = props("AdminClient")
    assert client["ExplicitAuthFlows"] == ["ALLOW_USER_AUTH"]
    assert client["AuthSessionValidity"] == 5
    assert client["SupportedIdentityProviders"] == ["COGNITO"]
    assert client["GenerateSecret"] is True
    assert client["EnablePropagateAdditionalUserContextData"] is True
    assert "EnablePropagateAdditionalUserContextData" not in props("CustomerClient")
    assert "DeviceConfiguration" not in props("AdminPool")
    assert not any(
        action in json.dumps(props("AdminOperatorPolicy"))
        for action in ("AdminInitiateAuth", "AdminRespondToAuthChallenge")
    )


def test_production_callback_cannot_use_localhost_or_wildcards():
    parameters = TEMPLATE["Parameters"]
    for origin in (
        "http://localhost:5173",
        "http://example.invalid",
        "https://*.example.invalid",
        "https://example.invalid/",
    ):
        assert re.fullmatch(parameters["AuthOrigin"]["AllowedPattern"], origin) is None
    assert re.fullmatch(
        parameters["AuthOrigin"]["AllowedPattern"], "https://popsibilities.example.invalid"
    )
    assert TEMPLATE["Rules"]["ProductionEmail"]["Assertions"][0]["Assert"] == {
        "Fn::Not": [{"Fn::Equals": [{"Ref": "AuthOrigin"}, ""]}]
    }
    for client_name, area, logout in [
        ("AdminClient", "admin", "/admin/login"),
        ("CustomerClient", "customer", "/login"),
    ]:
        client = props(client_name)
        callback = client["CallbackURLs"][0]["Fn::Sub"]
        assert callback[0] == "${EffectiveOrigin}/api/v1/" + area + "/callback"
        assert callback[1] == {
            "EffectiveOrigin": {
                "Fn::If": ["IsDevelopment", {"Ref": "DevelopmentOrigin"}, {"Ref": "AuthOrigin"}]
            }
        }
        assert client["LogoutURLs"][0]["Fn::Sub"][0] == "${EffectiveOrigin}" + logout


def test_managed_login_v2_and_default_branding_are_provisioned():
    for area in ("Admin", "Customer"):
        assert props(area + "Domain")["ManagedLoginVersion"] == 2
        assert props(area + "Branding")["ClientId"] == {"Ref": area + "Client"}
        assert props(area + "Branding")["UseCognitoProvidedValues"] is True


def test_compromised_passwords_and_high_risk_sign_ins_are_blocked():
    risk = props("AdminRiskConfiguration")
    assert props("AdminPool")["UserPoolAddOns"]["AdvancedSecurityMode"] == "ENFORCED"
    assert risk["CompromisedCredentialsRiskConfiguration"]["Actions"]["EventAction"] == "BLOCK"
    assert set(risk["CompromisedCredentialsRiskConfiguration"]["EventFilter"]) == {
        "SIGN_IN",
        "PASSWORD_CHANGE",
        "SIGN_UP",
    }
    assert risk["AccountTakeoverRiskConfiguration"]["Actions"] == {
        "HighAction": {"EventAction": "BLOCK", "Notify": False},
        "MediumAction": {"EventAction": "MFA_REQUIRED", "Notify": False},
        "LowAction": {"EventAction": "NO_ACTION", "Notify": False},
    }


def test_admin_logs_have_retention_and_supported_destination():
    logs = props("AdminAuthLogGroup")
    assert logs["RetentionInDays"] == 90
    assert logs["LogGroupName"]["Fn::Sub"].startswith("/aws/vendedlogs/")
    assert (
        "KmsKeyId" not in logs
    )  # Cognito's CloudWatch log delivery forbids a KMS-encrypted group.
    configuration = props("AdminLogDelivery")["LogConfigurations"][0]
    assert configuration["EventSource"] == "userAuthEvents" and configuration["LogLevel"] == "INFO"
    assert not configuration["CloudWatchLogsConfiguration"]["LogGroupArn"]["Fn::Sub"].endswith(":*")


def test_privileged_iam_actions_are_scoped_only_to_admin_pool():
    policy = props("AdminOperatorPolicy")
    assert "Roles" not in policy and "Users" not in policy and "Groups" not in policy
    statements = policy["PolicyDocument"]["Statement"]
    assert len(statements) == 1
    assert statements[0]["Resource"] == {"Fn::GetAtt": ["AdminPool", "Arn"]}
    assert set(statements[0]["Action"]) == {
        "cognito-idp:" + action
        for action in [
            "AdminCreateUser",
            "AdminGetUser",
            "AdminUserGlobalSignOut",
            "AdminDisableUser",
            "AdminDeleteSoftwareToken",
            "AdminSetUserPassword",
        ]
    }


def test_secrets_are_dynamic_references_and_never_outputs():
    for provider in ("GoogleProvider",):
        details = props(provider)["ProviderDetails"]
        for field in ("client_id", "client_secret"):
            assert (
                details[field]["Fn::Sub"]
                == "{{resolve:secretsmanager:${GoogleOAuthSecretArn}:SecretString:" + field + "}}"
            )
    outputs = json.dumps(TEMPLATE["Outputs"]).lower()
    assert (
        "clientsecret" not in outputs
        and "client_secret" not in outputs
        and "secretstring" not in outputs
    )
    assert "GoogleOAuthSecretArn" not in TEMPLATE["Outputs"]


def test_pools_retain_existing_identities_on_stack_removal_or_replacement():
    for name in ("CustomerPool", "AdminPool"):
        assert (
            RESOURCES[name]["DeletionPolicy"] == RESOURCES[name]["UpdateReplacePolicy"] == "Retain"
        )
        assert props(name)["DeletionProtection"] == "ACTIVE"
