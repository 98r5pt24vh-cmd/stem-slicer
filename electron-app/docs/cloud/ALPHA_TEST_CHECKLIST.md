# Slicer Cloud — checklist alpha locale

État préparé le 28 août 2026 : le projet Supabase, les comptes +NRGY et XT, leur connexion et une bibliothèque audio synthétique XT sont déjà prêts. Aucun fichier de la vraie bibliothèque n’a été envoyé.

## Test rapide dans Slicer

1. Ouvrir l’onglet **Cloud**.
2. Sélectionner **Use +NRGY** dans **Ready-to-test accounts**.
3. Dans **Profile**, ajouter une photo, une bio, Instagram et les alias du producteur, puis sélectionner **Save profile**.
4. Vérifier que la photo et les informations sauvegardées restent visibles après un changement d’onglet et après un redémarrage de Slicer.
5. Vérifier les états suivants :
   - XT est affiché comme connecté ;
   - dans **Producers**, XT utilise son profil Cloud et affiche sa photo distante lorsqu’elle existe ;
   - **XT Real Five Loops Test** contient 5 vraies loops et tous leurs layers réels, renommés `SLICER CLOUD XT TEST 01` à `05` ;
   - la bibliothèque est activée pour Generate.
6. Ouvrir **Generate** et garder une bibliothèque locale sélectionnée.
7. Ouvrir **Collaborators**.
8. Vérifier que XT apparaît avec la mention **Cloud** ou **Mac + Cloud**, ainsi qu’avec sa photo Cloud lorsqu’elle existe.
9. Activer **Duo**, autoriser XT, puis sélectionner **Require** sur la ligne XT.
10. Régler **Collaborator share** sur 100 % pour forcer les fixtures XT pendant ce test.
11. Garder les catégories Bass, Chords, Lead, Counter et Pluck, avec 140 BPM et F minor.
12. Lancer **Generate**.

Résultat attendu au premier lancement : Slicer télécharge uniquement les layers XT retenus, vérifie leur taille et leur empreinte SHA-256, puis les met en cache. La génération suivante doit réutiliser le cache au lieu de retélécharger les mêmes fichiers.

## Tester le second compte

1. Revenir dans **Cloud** et sélectionner **Sign out**.
2. Sélectionner **Use XT**.
3. Vérifier que +NRGY apparaît comme connecté et que **XT Real Five Loops Test** est la bibliothèque possédée par ce compte.
4. Sélectionner **Sign out**, puis **Use +NRGY** pour reprendre le test de génération.

Les boutons de test ne transmettent aucun mot de passe à l’interface. Le processus principal Electron lit les identifiants dans le cache local protégé, puis confie directement la connexion à Supabase Auth.

## Ce qui est déjà validé automatiquement

- lecture anonyme des catalogues refusée ;
- bibliothèque XT invisible à +NRGY avant acceptation ;
- bibliothèque et métadonnées visibles après acceptation ;
- bucket audio privé ;
- téléchargement authentifié d’un seul objet sélectionné ;
- réutilisation du fichier local après vérification SHA-256 ;
- 53 tests TypeScript et 11 tests Python réussis ;
- typecheck et ESLint réussis.

## Fondation du profil Cloud

- chaque profil peut enregistrer une photo, une bio de 280 caractères, un compte Instagram, jusqu’à 12 alias et un statut de disponibilité ;
- les photos sont normalisées en PNG par Slicer avant l’envoi ;
- le bucket public `profile-avatars` est limité à 5 Mo par objet et n’accepte que les PNG ;
- chaque utilisateur peut écrire uniquement dans son propre dossier de photos ;
- les alias Cloud consolident les crédits distants vers le nom principal du profil, par exemple `Tnex is R` vers `XT`.

## Données et limites de l’alpha

- Projet : **Slicer Cloud Alpha**, région West EU (Ireland).
- Corpus distant : 5 vraies loops de la bibliothèque locale et tous leurs layers MP3, copiés sous des noms de test explicites. Les originaux restent intacts.
- Supabase Auth est le système de comptes inclus au projet Supabase ; aucun second fournisseur de comptes n’est nécessaire pour cette alpha.
- Le plan gratuit offre actuellement 1 Go de Storage et 5 Go d’egress. Un objet du bucket alpha est limité à 50 Mo.
- Deux dossiers de 300 Mo représenteraient environ 600 Mo avant les métadonnées et les autres fichiers du projet.
- Cette étape ne produit pas encore de build Windows et n’envoie aucune vraie loop.

Références :

- [Supabase pricing](https://supabase.com/pricing)
- [Storage file limits](https://supabase.com/docs/guides/storage/uploads/file-limits)
- [Row Level Security](https://supabase.com/docs/guides/database/postgres/row-level-security)
- [API keys](https://supabase.com/docs/guides/getting-started/api-keys)
