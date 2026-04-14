

####  Users
Table centrale contenant les informations d'identité des utilisateurs.
* `id` : Identifiant unique de l’utilisateur.
* `email` : adresse email de l’utilisateur.
* `country` :  pays (code ou valeur).
* `status` : statut du compte utilisateur (codes numériques non documentés)
* `signup_date` : date d’inscription (formats hétérogènes détectés)
* `last_seen` : dernière activité de l’utilisateur.
* `referral_code` : code de parrainage.
* `phone_prefix` : indicatif téléphonique.

####  Payments
Table regroupant l’historique des transactions financières.
* `id` : Identifiant unique du paiement.
* `user_id` : Identifiant de l’utilisateur.
* `subscription_id` : Abonnement concerné.
* `amount_cents` : Montant du paiement (en centimes).
* `fee_cents` : Frais associés à la transaction.
* `status` : Statut du paiement (incohérences détectées : `success`, `succeeded`, `failed`, etc.).
* `created_at` : Date de création du paiement.
* `captured_at` : Date de validation du paiement (souvent manquante).
* `currency` : Devise utilisée.
* `stripe_error_code` : Code d’erreur technique en cas d’échec.

####  Memberships
Table représentant la participation des utilisateurs à des abonnements partagés.
* `id` : Identifiant du membership.
* `user_id` : Utilisateur concerné.
* `subscription_id` : Abonnement lié.
* `status` : État du membership (codes numériques à interpréter).
* `joined_at` : Date d’entrée dans l'abonnement.
* `left_at` : Date de sortie.
* `reason` : Raison de sortie (ex : `fraud`, `payment_failed`, etc.).

####  Complaints
Table contenant les plaintes entre utilisateurs de la plateforme.
* `id` : Identifiant de la plainte.
* `reporter_id` : Utilisateur qui dépose la plainte.
* `target_id` : Utilisateur visé par le signalement.
* `subscription_id` : Abonnement concerné.
* `type` : Nature de la plainte.
* `status` : État de la plainte (incohérences de format : `open`, `Open`, `RESOLVED`, etc.).
* `created_at` : Date de création.
* `resolved_at` : Date de résolution.
* `resolution` : Détail de la solution apportée.

####  Subscriptions
Table contenant les informations sur les abonnements collectifs proposés.
* `id` : Identifiant de l’abonnement.
* `brand` : Nom de la plateforme ou du service (ex: Netflix, Spotify).
* `owner_id` : Utilisateur propriétaire (responsable) de l’abonnement.
* `created_at` : Date de création du groupe.
* `status` : État actuel de l’abonnement.
* `max_slots` : Nombre maximum d’utilisateurs autorisés dans le groupe.
* `price_cents` : Prix total de l’abonnement.
* `currency` : Devise de facturation.


## 🕵️‍♂️ 2. Audit Exhaustif des Anomalies (Data Quality Report)

L'analyse du Notebook `exploration&clean_data.ipynb` a permis d'identifier des problèmes structurels profonds. Voici le rapport détaillé des anomalies par table avant nettoyage :

### 👤 Table `users`
* **Incohérences Temporelles (Dates) :** * **Formatage :** Les dates sont stockées sous des formats hétérogènes, rendant les calculs de durée impossibles sans conversion.
    * **Dates dans le futur :** Présence de dates de dernière connexion (`last_seen`) en 2026+.
    * **Anomalie Logique :** Plusieurs utilisateurs ont un `last_seen` antérieur à leur date d'inscription (`signup_date`), ce qui est physiquement impossible.
* **Standardisation Géographique :** * **Codes Pays (Country) :** Multiplicité des formats pour une même entité (ex: `FR`, `France`, `fr`). Nécessité d'une normalisation ISO.
    * **Téléphonie :** Désynchronisation entre le `country` et le `phone_prefix`. Certains préfixes ne correspondent pas au pays déclaré.
* **Problèmes d'Identité :**
    * **Doublon d'Email :** Un cas critique où un même email est rattaché à deux `user_id` différents (risque de faille de sécurité).
* **Opaque Status & Types :**
    * **Valeurs inconnues :** Présence de statuts `-1` et `99` sans aucune documentation, rendant l'état réel de l'utilisateur ambigu.
    * **Types de données :** Colonnes numériques stockées en texte et inversement, empêchant les agrégations directes.

###  Table `payments` 
* **Normalisation des Statuts :** Incohérences de saisie bloquantes entre `success` et `succeeded`, ainsi que des variations de casse (`failed` vs `Failed`).
* **Risques de Fraude masqués :** Présence de codes d'erreur Stripe critiques (`stolen_card`, `fraudulent`) sur des comptes d'utilisateurs n'ayant subi aucune sanction automatique.
* **Champs "Vides" :** La colonne `captured_at` est largement inexploitable (valeurs manquantes), rendant le suivi de la réconciliation bancaire impossible.
* **Card-Testing :** Identification d'utilisateurs avec un historique de tentatives de paiement dans plusieurs devises (`currency`) en un temps record.

###  Table `memberships` 
* **Codes Numériques Opaques :** Utilisation de statuts (0, 1, 2...) sans dictionnaire de correspondance, nécessitant un reverse-engineering des données.
* **Désynchronisation des Statuts :** Des utilisateurs possèdent une date de sortie (`left_at`) mais leur statut est toujours "Actif".
* **Rupture de communication :** Des motifs de sortie graves (`reason` = `fraud` ou `payment_failed`) sont enregistrés ici mais ne sont pas répercutés sur le compte utilisateur principal.

### Table `complaints` 
* **Nettoyage Textuel :** Statuts pollués par une casse hétérogène (`open`, `Open`, `RESOLVED`, `resolved`), faussant les statistiques de traitement.
* **Auto-Plaintes (Self-complaints) :** Anomalie où un utilisateur se signale lui-même (`reporter_id` = `target_id`).
* **Résolutions incomplètes :** Plaintes marquées comme "Résolues" mais dépourvues de date de résolution (`resolved_at`) ou de texte d'explication dans le champ `resolution`.

###  Table `subscriptions` 
* **Propriétaires Invalides :** Présence d'abonnements sans propriétaire identifiable (`owner_id` à 0 ou vide).
* **Dépassement de Capacité :** Certains abonnements présentent un nombre de membres actifs supérieur au `max_slots` autorisé par le service.