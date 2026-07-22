# Restricted Discord review policy

Sensitive review is disabled unless the read-only provisioning gate proves all of: a configured restricted parent channel, Adam's immutable Discord ID 552613509909971005, a signing secret, gateway allow-all disabled, and independently verified restricted membership.

Configuration values alone are insufficient membership proof. A failed or unavailable proof means no thread, post, mention, reminder, or scheduler activation. The system never creates a channel or changes Discord configuration.

Any future live transport must authenticate component/slash interactions and bind the action, pending ID, version, expiry, event ID, and Adam actor ID using the existing HMAC action contract. Natural-language text is not approval.
