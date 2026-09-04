-- MySQL dump 10.13  Distrib 8.4.9, for Linux (x86_64)
--
-- Host: db    Database: minamix
-- ------------------------------------------------------
-- Server version	8.4.9

/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!50503 SET NAMES utf8mb4 */;
/*!40103 SET @OLD_TIME_ZONE=@@TIME_ZONE */;
/*!40103 SET TIME_ZONE='+00:00' */;
/*!40014 SET @OLD_UNIQUE_CHECKS=@@UNIQUE_CHECKS, UNIQUE_CHECKS=0 */;
/*!40014 SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0 */;
/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */;
/*!40111 SET @OLD_SQL_NOTES=@@SQL_NOTES, SQL_NOTES=0 */;

--
-- Table structure for table `afk_users`
--

DROP TABLE IF EXISTS `afk_users`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `afk_users` (
  `user_id` bigint unsigned NOT NULL,
  `guild_id` bigint unsigned NOT NULL,
  `original_nick` varchar(32) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `reason` varchar(200) COLLATE utf8mb4_unicode_ci NOT NULL,
  `start_time` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `end_time` timestamp NULL DEFAULT NULL,
  PRIMARY KEY (`user_id`,`guild_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `afk_users`
--

LOCK TABLES `afk_users` WRITE;
/*!40000 ALTER TABLE `afk_users` DISABLE KEYS */;
/*!40000 ALTER TABLE `afk_users` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `antispam_channels`
--

DROP TABLE IF EXISTS `antispam_channels`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `antispam_channels` (
  `guild_id` bigint unsigned NOT NULL,
  `channel_id` bigint unsigned NOT NULL,
  PRIMARY KEY (`guild_id`,`channel_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `antispam_channels`
--

LOCK TABLES `antispam_channels` WRITE;
/*!40000 ALTER TABLE `antispam_channels` DISABLE KEYS */;
INSERT INTO `antispam_channels` VALUES (1437105431741730860,1457092570135134300);
/*!40000 ALTER TABLE `antispam_channels` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `boutique_roles`
--

DROP TABLE IF EXISTS `boutique_roles`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `boutique_roles` (
  `id` int NOT NULL AUTO_INCREMENT,
  `role_id` bigint NOT NULL,
  `prix` int NOT NULL,
  `nom` varchar(255) NOT NULL,
  `description` text,
  `exclusif` tinyint(1) NOT NULL DEFAULT '0',
  PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=25 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `boutique_roles`
--

LOCK TABLES `boutique_roles` WRITE;
/*!40000 ALTER TABLE `boutique_roles` DISABLE KEYS */;
INSERT INTO `boutique_roles` VALUES (3,1437105432278728778,3000,'Plèbe',NULL,0),(5,1437105432278728777,6000,'Pauvre',NULL,0),(6,1437105432278728776,8500,'Classe moyenne',NULL,0),(7,1437105432278728775,11500,'Noble',NULL,0),(8,1437105432257888285,14000,'Je suis riche',NULL,0),(9,1437105432257888284,17000,'Millionaire',NULL,0),(10,1437105432257888283,19500,'Je suis Picsou',NULL,0),(13,1437105432257888282,15000,'Roc de Galdros',NULL,0),(14,1437105432257888281,15000,'Bougie d\'Ignis',NULL,0),(15,1437105432257888279,15000,'Vague de Nyrel',NULL,0),(16,1437105432257888280,15000,'Tourbillon de Zoggan',NULL,0),(17,1437105432257888278,15000,'Racine de Sylvaë',NULL,0),(18,1437105432257888277,15000,'Lueur de Vespera',NULL,0),(19,1437105432257888276,15000,'Cauchemar de Noctis',NULL,0),(20,1437105432224338009,15000,'Manipulateur de Whimir',NULL,0),(21,1437105432224338007,20000,'Chasseur de Gloomstorms',NULL,1),(23,1437105432224338006,20000,'Dresseurs de Drakei',NULL,1),(24,1437105432224338005,20000,'Témoins de l\'aube',NULL,1);
/*!40000 ALTER TABLE `boutique_roles` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `discoveries`
--

DROP TABLE IF EXISTS `discoveries`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `discoveries` (
  `user_id` bigint unsigned NOT NULL,
  `egg_key` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `found_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`user_id`,`egg_key`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `discoveries`
--

LOCK TABLES `discoveries` WRITE;
/*!40000 ALTER TABLE `discoveries` DISABLE KEYS */;
INSERT INTO `discoveries` VALUES (541212803441229824,'l_accord','2026-05-31 12:59:04'),(541212803441229824,'l_essentiel','2026-05-23 18:27:40'),(541212803441229824,'l_insomniaque','2026-05-26 04:38:19'),(831781576030945323,'l_accord','2026-06-26 14:00:58'),(840870799064956930,'champion','2026-05-23 15:08:39'),(840870799064956930,'l_accord','2026-05-23 15:10:17'),(840870799064956930,'l_essentiel','2026-05-23 15:10:05'),(840870799064956930,'l_hibiscus','2026-05-23 21:57:05'),(840870799064956930,'le_seigneur','2026-05-23 15:09:01'),(1058451360292544594,'l_essentiel','2026-05-29 22:55:39');
/*!40000 ALTER TABLE `discoveries` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `guild_config`
--

DROP TABLE IF EXISTS `guild_config`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `guild_config` (
  `guild_id` bigint unsigned NOT NULL,
  `config_key` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `value` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  PRIMARY KEY (`guild_id`,`config_key`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `guild_config`
--

LOCK TABLES `guild_config` WRITE;
/*!40000 ALTER TABLE `guild_config` DISABLE KEYS */;
INSERT INTO `guild_config` VALUES (1437105431741730860,'afk_logs_channel','1508248666299826186'),(1437105431741730860,'logs_channel','1437105433050349787'),(1437105431741730860,'rp_channel','1508559675271020685'),(1437105431741730860,'warn_logs_channel','1437105433050349787'),(1482529716463210506,'afk_logs_channel','1482529717511782592');
/*!40000 ALTER TABLE `guild_config` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `rp_characters`
--

DROP TABLE IF EXISTS `rp_characters`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `rp_characters` (
  `id` int NOT NULL AUTO_INCREMENT,
  `guild_id` bigint unsigned NOT NULL,
  `user_id` bigint unsigned NOT NULL,
  `name` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `prefix` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL,
  `image_url` varchar(500) COLLATE utf8mb4_unicode_ci NOT NULL,
  `created_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
  `nax_balance` bigint NOT NULL DEFAULT '0',
  PRIMARY KEY (`id`),
  UNIQUE KEY `unique_prefix_guild` (`guild_id`,`prefix`)
) ENGINE=InnoDB AUTO_INCREMENT=2 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `rp_characters`
--

LOCK TABLES `rp_characters` WRITE;
/*!40000 ALTER TABLE `rp_characters` DISABLE KEYS */;
INSERT INTO `rp_characters` VALUES (1,1437105431741730860,840870799064956930,'Jose Balden','JB:','https://cdn.discordapp.com/ephemeral-attachments/1508561691707703467/1508563146950971463/jb.jpg?ex=6a15fe69&is=6a14ace9&hm=db3d2323312188a0b9b66f2d9b646c5d4311a8e043889b0ed08a8792be08c75c&','2026-05-25 20:11:24',500);
/*!40000 ALTER TABLE `rp_characters` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `users`
--

DROP TABLE IF EXISTS `users`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `users` (
  `user_id` bigint unsigned NOT NULL,
  `last_work` bigint NOT NULL DEFAULT '0',
  `last_seen` timestamp NULL DEFAULT NULL,
  PRIMARY KEY (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `users`
--

LOCK TABLES `users` WRITE;
/*!40000 ALTER TABLE `users` DISABLE KEYS */;
INSERT INTO `users` VALUES (347687648418332673,0,'2026-06-28 20:05:45'),(541212803441229824,1779483333,'2026-08-31 21:15:46'),(598070479689089034,0,'2026-08-12 19:16:14'),(797160753022763080,0,'2026-06-28 13:07:00'),(831781576030945323,0,'2026-07-02 17:07:58'),(840870799064956930,1779483570,'2026-07-02 19:04:50'),(919653166629404742,0,'2026-06-28 13:07:42'),(961042202941878272,0,'2026-06-29 19:17:23'),(985192249220562994,0,'2026-08-19 17:09:28'),(998881686492287086,0,'2026-06-11 14:58:22'),(1022283248702869604,1779903909,'2026-06-26 22:21:21'),(1058451360292544594,0,'2026-06-28 15:57:36');
/*!40000 ALTER TABLE `users` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `wallets`
--

DROP TABLE IF EXISTS `wallets`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `wallets` (
  `user_id` bigint unsigned NOT NULL,
  `balance` bigint NOT NULL DEFAULT '0',
  `updated_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `wallets`
--

LOCK TABLES `wallets` WRITE;
/*!40000 ALTER TABLE `wallets` DISABLE KEYS */;
INSERT INTO `wallets` VALUES (347687648418332673,659,'2026-06-28 20:05:45'),(541212803441229824,800000011968,'2026-08-31 21:15:46'),(598070479689089034,20,'2026-08-12 19:16:14'),(797160753022763080,871,'2026-06-28 13:11:00'),(831781576030945323,435,'2026-07-02 17:07:58'),(840870799064956930,6999449,'2026-07-02 19:04:50'),(919653166629404742,108,'2026-06-28 13:07:42'),(961042202941878272,2014,'2026-06-29 19:17:23'),(985192249220562994,2781,'2026-08-19 17:09:28'),(998881686492287086,91,'2026-06-11 15:00:56'),(1022283248702869604,308,'2026-06-26 22:21:21'),(1058451360292544594,1320,'2026-06-28 15:57:36');
/*!40000 ALTER TABLE `wallets` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `warnings`
--

DROP TABLE IF EXISTS `warnings`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `warnings` (
  `id` int NOT NULL AUTO_INCREMENT,
  `user_id` bigint unsigned NOT NULL,
  `guild_id` bigint unsigned NOT NULL,
  `moderator_id` bigint unsigned NOT NULL,
  `reason` varchar(500) COLLATE utf8mb4_unicode_ci NOT NULL,
  `created_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_user_guild` (`user_id`,`guild_id`)
) ENGINE=InnoDB AUTO_INCREMENT=4 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `warnings`
--

LOCK TABLES `warnings` WRITE;
/*!40000 ALTER TABLE `warnings` DISABLE KEYS */;
INSERT INTO `warnings` VALUES (1,541212803441229824,1437105431741730860,840870799064956930,'Il a changé la couleur de mon rôle et maman m\'a dit que ce n\'était pas gentil d\'être méchant.','2026-05-24 18:59:36');
/*!40000 ALTER TABLE `warnings` ENABLE KEYS */;
UNLOCK TABLES;
/*!40103 SET TIME_ZONE=@OLD_TIME_ZONE */;

/*!40101 SET SQL_MODE=@OLD_SQL_MODE */;
/*!40014 SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS */;
/*!40014 SET UNIQUE_CHECKS=@OLD_UNIQUE_CHECKS */;
/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
/*!40111 SET SQL_NOTES=@OLD_SQL_NOTES */;

-- Dump completed on 2026-09-04 23:06:19
