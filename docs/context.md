# **Cas pratique –** Chief of Staff Direction des Opérations

# **Cas pratique – Web app interne "Risk Monitor"**

### 🎯 **Objectif**

Concevoir et livrer un **outil interne de détection et traitement des abonnés à risque** pour une marketplace d'abonnements partagés. L'outil doit combiner scoring data, interface opérationnelle et intelligence artificielle — le tout sur des données volontairement imparfaites.

Ce cas est conçu pour être **difficile**. On ne cherche pas quelqu'un qui empile des features : on cherche quelqu'un qui sait faire des choix sous contrainte, documenter ses compromis, et livrer un truc qui fonctionne.

---

## 👨‍💻 **Contexte métier**

Tu travailles pour une **marketplace d'abonnements partagés**. Le modèle :

- Un **owner** partage son abonnement (Netflix, Spotify, etc.)
- Des **subscribers** le rejoignent et paient une part mensuelle
- La plateforme prélève une **commission (fee)** sur chaque paiement
- En cas de problème, un subscriber ou un owner peut ouvrir une **réclamation (issue)**

**Le problème :** certains subscribers ont un comportement toxique — échecs de paiement répétés, réclamations multiples, changements d'abonnements fréquents. Ça coûte cher (frais Stripe sur les échecs, temps support, churn des owners). L'équipe opérations gère ça manuellement. Ce n'est pas scalable.

---

## 📦 **Données fournies**

Tu recevras un **fichier SQLite** contenant 5 tables. Les données sont **anonymisées et volontairement dégradées** :

- Certains champs contiennent des **valeurs incohérentes ou manquantes**
- Les **timestamps** ne sont pas tous dans le même fuseau horaire
- Certaines lignes sont des **doublons partiels** (même user, même abo, statuts contradictoires)
- Un champ `status` utilise des **codes numériques non documentés** — à toi de les reverse-engineer à partir des données

Tables : `users`, `subscriptions`, `memberships`, `payments`, `complaints`

> Aucun dictionnaire de données n'est fourni. Tu dois explorer, déduire, documenter tes hypothèses. C'est voulu.
> 

---

## 🔧 **Les 4 épreuves**

### Épreuve 1 — Data cleaning & exploration (obligatoire)

Avant de scorer quoi que ce soit, tu dois **nettoyer et comprendre les données**.

- Documenter les anomalies trouvées (incohérences, doublons, valeurs manquantes)
- Expliquer comment tu les traites (suppression, imputation, flag…) et **pourquoi**
- Produire un **notebook exploratoire** (Jupyter ou équivalent) montrant ta démarche — pas juste le résultat final

> On veut voir ton processus, pas un CSV propre tombé du ciel.
> 

### Épreuve 2 — Scoring (obligatoire)

Construire un **risk score** par subscriber. Aucun critère n'est imposé.

- Tu dois **définir tes propres features**, les justifier, et expliquer leur pondération
- Le score doit être **reproductible** : même données → même score (pas de random, pas de dépendance à un appel LLM)
- Gérer les **edge cases** : nouveau subscriber sans historique, subscriber avec un seul paiement réussi, subscriber inactif depuis 6 mois…
- **Livrable** : une fonction ou un script qui prend le SQLite en entrée et produit un CSV scoré en sortie, exécutable en une commande

### Épreuve 3 — Interface (obligatoire)

Construire une **interface web fonctionnelle** permettant à un opérateur de :

- Voir la liste des subscribers triés par risk score
- Filtrer (par score, statut, date, pays…)
- Cliquer sur un subscriber pour voir son **historique détaillé** (paiements, changements de statut, réclamations)
- Effectuer une action (au minimum : marquer comme "à surveiller" ou "à bloquer")

Contraintes :

- L'interface doit être **utilisable sans documentation** — si un opérateur non-tech ne peut pas comprendre en 30 secondes ce qu'il voit, c'est raté
- Pas de template CSS brut / Bootstrap générique — on veut voir un minimum d'effort sur l'UX
- L'état des actions (surveillé / bloqué) doit **persister** (pas disparaître au refresh)

### Épreuve 4 — Agent IA (obligatoire)

C'est la partie la plus exigeante. Tu dois intégrer un **agent IA** (Claude, GPT, ou open-source) qui remplit **au moins deux** de ces rôles :

**a) Analyste** — Quand un opérateur consulte un profil, l'agent génère un **résumé structuré** du cas : comportement observé, signaux d'alerte, comparaison avec les comportements moyens de la base. Pas un résumé bateau — un résumé qui aide réellement à décider.

**b) Décideur** — L'agent propose une **recommandation d'action** (surveiller / avertir / bloquer / ignorer) avec un **niveau de confiance** et une **justification**. L'opérateur peut accepter ou rejeter. Les décisions rejetées doivent être loggées pour analyse ultérieure.

**c) Détecteur de patterns** — L'agent analyse la base entière (ou un échantillon) et identifie des **clusters de comportements suspects** qui ne seraient pas visibles avec un scoring classique. Exemple : 5 subscribers qui rejoignent le même owner à quelques minutes d'intervalle.

**Ce qu'on évalue :**

- La **pertinence du prompt** : est-ce qu'il donne au LLM le bon contexte avec les bonnes contraintes ?
- La **gestion des limites** : que se passe-t-il si le LLM hallucine ? Si l'API est down ? Si le contexte est trop long ?
- Le **coût** : as-tu réfléchi au nombre de tokens consommés ? As-tu mis un cache, une limite, un fallback ?
- La **traçabilité** : chaque appel IA est-il loggé avec l'input, l'output, le modèle, et le coût estimé ?

---

## 🚫 **Contraintes**

- **Pas de maquette Figma** — du code qui tourne
- **Pas de "TODO" dans le code livré** — si une feature n'est pas faite, ne la mentionne pas dans le code. Documente-la dans ta doc comme évolution possible
- **Un seul `README.md`** doit suffire pour lancer le projet (setup + run en moins de 5 commandes)
- **Pas de clé API en dur** — variables d'environnement, `.env.example` fourni

---

## ✅ **Livrables**

1. **Repo GitHub** — code structuré, commits atomiques (on regarde l'historique)
2. **Notebook exploratoire** — ta démarche de data cleaning, pas juste le résultat
3. **App déployée** (Render, Railway, Vercel…) ou exécutable en local via Docker
4. [**README.md**](http://README.md) — hypothèses sur les données, choix techniques argumentés, architecture, limites connues, pistes d'évolution
5. **Prompt(s) IA versionnés** — dans un dossier `/prompts` avec explication de chaque itération

> La qualité de ta documentation compte autant que ton code. Un projet partiel bien documenté bat un projet "complet" sans explication.
> 

---

## 🧠 **Grille d'évaluation**

| Critère | Poids | Ce qu'on regarde |
| --- | --- | --- |
| **Data cleaning & rigueur** | 20% | Anomalies identifiées, traitement justifié, notebook clair |
| **Scoring** | 20% | Pertinence des features, gestion des edge cases, reproductibilité |
| **Interface** | 20% | Utilisabilité, UX, persistance, filtres fonctionnels |
| **Agent IA** | 25% | Pertinence du prompt, gestion des limites, traçabilité, coût |
| **Documentation & communication** | 15% | README, commits, choix argumentés, honnêteté sur les limites |

---

## 📦 **Jeu de données**

Télécharge le fichier ci-dessous et utilise-le comme source de données pour l'exercice.

👉 **risk_monitor_[dataset.zip](http://dataset.zip)**

[risk_monitor_dataset.sqlite.zip](attachment:425ca43d-78a0-4f95-9cb4-2a4fbbb11544:risk_monitor_dataset.sqlite.zip)

Le fichier contient une base SQLite avec 5 tables : `users`, `subscriptions`, `memberships`, `payments`, `complaints`. Aucun dictionnaire de données n'est fourni — c'est voulu.

---

## ⏱ **Deadline**

**72h** après réception du jeu de données.

> Ce cas est volontairement ambitieux. On ne s'attend pas à ce que tout soit parfait. On s'attend à ce que tu fasses des choix intelligents sur ce que tu priorises, que tu documentes ce que tu n'as pas eu le temps de faire, et que tu livres quelque chose qui tourne.
> 

> **Dernier conseil** : on sait que tu vas utiliser de l'IA pour t'aider à coder. C'est normal, on le fait aussi. Ce qui fera la différence, c'est ta capacité à comprendre ce que tu livres, à identifier les failles, et à prendre des décisions que l'IA ne peut pas prendre à ta place.
>