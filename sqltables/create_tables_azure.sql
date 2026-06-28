-- ============================================================
-- Azure SQL DDL Script for diving-eval v2
-- Migrated from Supabase/PostgreSQL
-- 
-- NOTES on Supabase export quirk:
--   Several lookup tables (pisterefcomppoints, pistereftrainingsince,
--   pistereftrainingtime) were exported with VALUES in physical storage
--   order (numeric columns first, id/age last), while the INSERT column
--   list shows id/age first. Handle this in data migration scripts.
--
-- PostgreSQL -> T-SQL conversions applied:
--   UUID           -> UNIQUEIDENTIFIER
--   boolean        -> BIT  (true=1, false=0)
--   text/varchar   -> NVARCHAR
--   SERIAL         -> INT IDENTITY(1,1)
--   timestamp      -> DATETIME2
--   Column names with %, -, or numbers -> [bracket-escaped]
-- ============================================================

-- Drop tables in dependency order (FKs: pisteresults -> athletes, pistedisciplines)
IF OBJECT_ID('dbo.pisteresults','U')          IS NOT NULL DROP TABLE dbo.pisteresults;
IF OBJECT_ID('dbo.athletes','U')              IS NOT NULL DROP TABLE dbo.athletes;
IF OBJECT_ID('dbo.pistedisciplines','U')      IS NOT NULL DROP TABLE dbo.pistedisciplines;
IF OBJECT_ID('dbo.scoretables','U')           IS NOT NULL DROP TABLE dbo.scoretables;
IF OBJECT_ID('dbo.agecategories','U')         IS NOT NULL DROP TABLE dbo.agecategories;
IF OBJECT_ID('dbo.agecategorieshd','U')       IS NOT NULL DROP TABLE dbo.agecategorieshd;
IF OBJECT_ID('dbo.agedives','U')              IS NOT NULL DROP TABLE dbo.agedives;
IF OBJECT_ID('dbo.competitions','U')          IS NOT NULL DROP TABLE dbo.competitions;
IF OBJECT_ID('dbo.compresults','U')           IS NOT NULL DROP TABLE dbo.compresults;
IF OBJECT_ID('dbo.compresultsbig','U')        IS NOT NULL DROP TABLE dbo.compresultsbig;
IF OBJECT_ID('dbo.pisterefcomppoints','U')    IS NOT NULL DROP TABLE dbo.pisterefcomppoints;
IF OBJECT_ID('dbo.pisterefcompresults','U')   IS NOT NULL DROP TABLE dbo.pisterefcompresults;
IF OBJECT_ID('dbo.pisterefminpoints','U')     IS NOT NULL DROP TABLE dbo.pisterefminpoints;
IF OBJECT_ID('dbo.pistereftrainingsince','U') IS NOT NULL DROP TABLE dbo.pistereftrainingsince;
IF OBJECT_ID('dbo.pistereftrainingtime','U')  IS NOT NULL DROP TABLE dbo.pistereftrainingtime;
IF OBJECT_ID('dbo.pisteenvironment','U')      IS NOT NULL DROP TABLE dbo.pisteenvironment;
IF OBJECT_ID('dbo.pistemirwald','U')          IS NOT NULL DROP TABLE dbo.pistemirwald;
IF OBJECT_ID('dbo.selectionpoints','U')       IS NOT NULL DROP TABLE dbo.selectionpoints;
IF OBJECT_ID('dbo.athleteyearstatus','U')     IS NOT NULL DROP TABLE dbo.athleteyearstatus;
IF OBJECT_ID('dbo.socadditionalvalues','U')   IS NOT NULL DROP TABLE dbo.socadditionalvalues;
IF OBJECT_ID('dbo.team','U')                  IS NOT NULL DROP TABLE dbo.team;
IF OBJECT_ID('dbo.trainingsperformance','U')  IS NOT NULL DROP TABLE dbo.trainingsperformance;
GO

-- ============================================================
-- Reference / lookup tables
-- ============================================================

CREATE TABLE dbo.agecategories (
    id           UNIQUEIDENTIFIER NOT NULL PRIMARY KEY DEFAULT NEWID(),
    min_age      INT              NULL,
    max_age      INT              NULL,
    category     NVARCHAR(100)    NULL
);
GO

CREATE TABLE dbo.agecategorieshd (
    id       INT           NOT NULL PRIMARY KEY,
    min_age  INT           NULL,
    mag_age  INT           NULL,   -- note: typo in source schema (was "mag_age", not "max_age")
    category NVARCHAR(100) NULL
);
GO

CREATE TABLE dbo.agedives (
    id         INT           NOT NULL PRIMARY KEY,
    Discipline NVARCHAR(100) NULL,
    sex        NVARCHAR(20)  NULL,
    category   NVARCHAR(100) NULL,
    dives      INT           NULL
);
GO

CREATE TABLE dbo.pistedisciplines (
    id   UNIQUEIDENTIFIER NOT NULL PRIMARY KEY DEFAULT NEWID(),
    name NVARCHAR(100)    NULL,
    unit NVARCHAR(50)     NULL
);
GO

CREATE TABLE dbo.scoretables (
    id            UNIQUEIDENTIFIER NOT NULL PRIMARY KEY DEFAULT NEWID(),
    discipline_id UNIQUEIDENTIFIER NULL,
    result_max    NVARCHAR(50)     NULL,
    points        FLOAT            NULL,
    sex           NVARCHAR(20)     NULL,
    result_min    NVARCHAR(50)     NULL,
    category      NVARCHAR(100)    NULL
);
GO

CREATE TABLE dbo.team (
    id        INT           NOT NULL PRIMARY KEY,
    FullName  NVARCHAR(255) NULL,
    ShortName NVARCHAR(100) NULL
);
GO

-- ============================================================
-- Athletes
-- ============================================================

CREATE TABLE dbo.athletes (
    id           UNIQUEIDENTIFIER NOT NULL PRIMARY KEY DEFAULT NEWID(),
    first_name   NVARCHAR(100)    NULL,
    last_name    NVARCHAR(100)    NULL,
    birthdate    DATE             NULL,
    club         NVARCHAR(255)    NULL,
    full_name    NVARCHAR(255)    NULL,
    category     NVARCHAR(100)    NULL,
    sex          NVARCHAR(20)     NULL,
    nationalteam NVARCHAR(10)     NULL,
    vintage      NVARCHAR(10)     NULL,
    bioage       NVARCHAR(20)     NULL
);
GO

-- ============================================================
-- Competitions
-- ============================================================

CREATE TABLE dbo.competitions (
    id               INT           NOT NULL PRIMARY KEY,
    Name             NVARCHAR(255) NULL,
    Date             DATE          NULL,
    [qual-Regional]  BIT           NULL,
    [qual-National]  BIT           NULL,
    [qual-JEM]       BIT           NULL,
    [qual-EM]        BIT           NULL,
    [qual-WM]        BIT           NULL,
    [qual-Piste]     BIT           NULL,
    Type             NVARCHAR(50)  NULL,
    PisteYear        NVARCHAR(10)  NULL
);
GO

-- ============================================================
-- Competition results
-- ============================================================

CREATE TABLE dbo.compresults (
    id                   INT           NOT NULL PRIMARY KEY,
    first_name           NVARCHAR(100) NULL,
    last_name            NVARCHAR(100) NULL,
    Competition          NVARCHAR(255) NULL,
    Discipline           NVARCHAR(100) NULL,
    CategoryStart        NVARCHAR(100) NULL,
    PreFin               NVARCHAR(50)  NULL,
    Points               NVARCHAR(50)  NULL,
    Difficulty           NVARCHAR(50)  NULL,
    AveragePoints        NVARCHAR(50)  NULL,
    JEM                  NVARCHAR(50)  NULL,
    [JEM%]               NVARCHAR(50)  NULL,
    EM                   NVARCHAR(50)  NULL,
    [EM%]                NVARCHAR(50)  NULL,
    WM                   NVARCHAR(50)  NULL,
    [WM%]                NVARCHAR(50)  NULL,
    sex                  NVARCHAR(20)  NULL,
    timestamp            NVARCHAR(50)  NULL,
    [PisteRefPoints2024%] NVARCHAR(50) NULL,
    [PisteRefPoints2025%] NVARCHAR(50) NULL,
    [PisteRefPoints2026%] NVARCHAR(50) NULL,
    [PisteRefPoints2027%] NVARCHAR(50) NULL,
    [PisteRefPoints2028%] NVARCHAR(50) NULL,
    [PisteRefPoints2029%] NVARCHAR(50) NULL,
    [PisteRefPoints2030%] NVARCHAR(50) NULL,
    RegionalTeam         NVARCHAR(10)  NULL,
    NationalTeam         NVARCHAR(10)  NULL
);
GO

CREATE TABLE dbo.compresultsbig (
    id         INT           NOT NULL PRIMARY KEY,
    competition NVARCHAR(255) NULL,
    year        NVARCHAR(10)  NULL,
    discipline  NVARCHAR(100) NULL,
    category    NVARCHAR(100) NULL,
    sex         NVARCHAR(20)  NULL,
    rank        NVARCHAR(20)  NULL,   -- can be numeric or 'QualF' etc.
    points      NVARCHAR(50)  NULL
);
GO

CREATE TABLE dbo.selectionpoints (
    id          INT           NOT NULL PRIMARY KEY,
    Competition NVARCHAR(255) NULL,
    year        NVARCHAR(10)  NULL,
    Discipline  NVARCHAR(100) NULL,
    sex         NVARCHAR(20)  NULL,
    points      NVARCHAR(50)  NULL,
    difficulty  NVARCHAR(50)  NULL,
    category    NVARCHAR(100) NULL
);
GO

-- ============================================================
-- PISTE results (linked to athletes + disciplines)
-- ============================================================

CREATE TABLE dbo.pisteresults (
    id            UNIQUEIDENTIFIER NOT NULL PRIMARY KEY DEFAULT NEWID(),
    athlete_id    UNIQUEIDENTIFIER NULL,
    discipline_id UNIQUEIDENTIFIER NULL,
    raw_result    DECIMAL(10,4)    NULL,
    TestYear      NVARCHAR(10)     NULL,
    category      NVARCHAR(100)    NULL,
    points        DECIMAL(10,4)    NULL,
    sex           NVARCHAR(20)     NULL,
    CONSTRAINT FK_pisteresults_athlete    FOREIGN KEY (athlete_id)    REFERENCES dbo.athletes(id),
    CONSTRAINT FK_pisteresults_discipline FOREIGN KEY (discipline_id) REFERENCES dbo.pistedisciplines(id)
);
GO

-- ============================================================
-- PISTE reference tables
-- NOTE: Supabase export ordering quirk - when migrating data,
-- use explicit column mapping in INSERT statements.
-- ============================================================

-- Competition reference points by discipline / sex / age group
-- Columns [8]..[19] = age-group score thresholds
-- quality[8]..quality[19] = derived quality values
CREATE TABLE dbo.pisterefcomppoints (
    id          INT           NOT NULL PRIMARY KEY,
    Discipline  NVARCHAR(50)  NULL,
    sex         NVARCHAR(20)  NULL,
    [8]         DECIMAL(10,4) NULL,
    [9]         DECIMAL(10,4) NULL,
    [10]        DECIMAL(10,4) NULL,
    [11]        DECIMAL(10,4) NULL,
    [12]        DECIMAL(10,4) NULL,
    [13]        DECIMAL(10,4) NULL,
    [14]        DECIMAL(10,4) NULL,
    [15]        DECIMAL(10,4) NULL,
    [16]        DECIMAL(10,4) NULL,
    [17]        DECIMAL(10,4) NULL,
    [18]        DECIMAL(10,4) NULL,
    [19]        DECIMAL(10,4) NULL,
    quality8    DECIMAL(10,4) NULL,
    quality9    DECIMAL(10,4) NULL,
    quality10   DECIMAL(10,4) NULL,
    quality11   DECIMAL(10,4) NULL,
    quality12   DECIMAL(10,4) NULL,
    quality13   DECIMAL(10,4) NULL,
    quality14   DECIMAL(10,4) NULL,
    quality15   DECIMAL(10,4) NULL,
    quality16   DECIMAL(10,4) NULL,
    quality17   DECIMAL(10,4) NULL,
    quality18   DECIMAL(10,4) NULL,
    quality19   DECIMAL(10,4) NULL
);
GO

-- Aggregate competition results per athlete for PISTE evaluation
CREATE TABLE dbo.pisterefcompresults (
    id                    INT           NOT NULL PRIMARY KEY,
    first_name            NVARCHAR(100) NULL,
    last_name             NVARCHAR(100) NULL,
    age                   NVARCHAR(50)  NULL,
    competition1          NVARCHAR(255) NULL,
    discipline1           NVARCHAR(100) NULL,
    points1               NVARCHAR(50)  NULL,
    reference1            NVARCHAR(50)  NULL,
    competition2          NVARCHAR(255) NULL,
    discipline2           NVARCHAR(100) NULL,
    points2               NVARCHAR(50)  NULL,
    reference2            NVARCHAR(50)  NULL,
    competition3          NVARCHAR(255) NULL,
    discipline3           NVARCHAR(100) NULL,
    points3               NVARCHAR(50)  NULL,
    reference3            NVARCHAR(50)  NULL,
    refaverage            NVARCHAR(50)  NULL,
    PisteYear             NVARCHAR(10)  NULL,
    performance           NVARCHAR(50)  NULL,
    pointsaverage1        NVARCHAR(50)  NULL,
    pointsaverage2        NVARCHAR(50)  NULL,
    pointsaverage3        NVARCHAR(50)  NULL,
    pointsaverageaverage  NVARCHAR(50)  NULL,
    [pointsaverageref%]   NVARCHAR(50)  NULL,
    quality               NVARCHAR(50)  NULL
);
GO

-- Minimum points required by age for regional/national selection
CREATE TABLE dbo.pisterefminpoints (
    id          INT           NOT NULL PRIMARY KEY,
    age         NVARCHAR(50)  NULL,
    points_max  NVARCHAR(50)  NULL,
    regio_min   NVARCHAR(50)  NULL,
    national_min NVARCHAR(50) NULL
);
GO

-- Reference points by training duration (years) per age group
-- Columns [0]..[14] = training duration thresholds
CREATE TABLE dbo.pistereftrainingsince (
    id   INT           NOT NULL PRIMARY KEY,
    age  INT           NULL,
    [0]  DECIMAL(10,4) NULL,
    [1]  DECIMAL(10,4) NULL,
    [2]  DECIMAL(10,4) NULL,
    [3]  DECIMAL(10,4) NULL,
    [4]  DECIMAL(10,4) NULL,
    [5]  DECIMAL(10,4) NULL,
    [6]  DECIMAL(10,4) NULL,
    [7]  DECIMAL(10,4) NULL,
    [8]  DECIMAL(10,4) NULL,
    [9]  DECIMAL(10,4) NULL,
    [10] DECIMAL(10,4) NULL,
    [11] DECIMAL(10,4) NULL,
    [12] DECIMAL(10,4) NULL,
    [13] DECIMAL(10,4) NULL,
    [14] DECIMAL(10,4) NULL
);
GO

-- Reference points by weekly training hours per age group
-- Columns [4]..[30] = weekly training time thresholds
CREATE TABLE dbo.pistereftrainingtime (
    id   INT           NOT NULL PRIMARY KEY,
    age  INT           NULL,
    [4]  DECIMAL(10,4) NULL,
    [5]  DECIMAL(10,4) NULL,
    [6]  DECIMAL(10,4) NULL,
    [7]  DECIMAL(10,4) NULL,
    [8]  DECIMAL(10,4) NULL,
    [9]  DECIMAL(10,4) NULL,
    [10] DECIMAL(10,4) NULL,
    [11] DECIMAL(10,4) NULL,
    [12] DECIMAL(10,4) NULL,
    [13] DECIMAL(10,4) NULL,
    [14] DECIMAL(10,4) NULL,
    [15] DECIMAL(10,4) NULL,
    [16] DECIMAL(10,4) NULL,
    [17] DECIMAL(10,4) NULL,
    [18] DECIMAL(10,4) NULL,
    [19] DECIMAL(10,4) NULL,
    [20] DECIMAL(10,4) NULL,
    [21] DECIMAL(10,4) NULL,
    [22] DECIMAL(10,4) NULL,
    [23] DECIMAL(10,4) NULL,
    [24] DECIMAL(10,4) NULL,
    [25] DECIMAL(10,4) NULL,
    [26] DECIMAL(10,4) NULL,
    [27] DECIMAL(10,4) NULL,
    [28] DECIMAL(10,4) NULL,
    [29] DECIMAL(10,4) NULL,
    [30] DECIMAL(10,4) NULL
);
GO

-- ============================================================
-- SOC / Athlete evaluation tables
-- ============================================================

CREATE TABLE dbo.pisteenvironment (
    id           INT           NOT NULL PRIMARY KEY,
    first_name   NVARCHAR(100) NULL,
    last_name    NVARCHAR(100) NULL,
    birthdate    DATE          NULL,
    PisteYear    NVARCHAR(10)  NULL,
    toolenvvalue NVARCHAR(50)  NULL
);
GO

CREATE TABLE dbo.pistemirwald (
    id           INT           NOT NULL PRIMARY KEY,
    first_name   NVARCHAR(100) NULL,
    last_name    NVARCHAR(100) NULL,
    PisteYear    NVARCHAR(10)  NULL,
    bioentwstand NVARCHAR(50)  NULL
);
GO

CREATE TABLE dbo.trainingsperformance (
    id           INT           NOT NULL PRIMARY KEY,
    first_name   NVARCHAR(100) NULL,
    last_name    NVARCHAR(100) NULL,
    q1           DECIMAL(10,4) NULL,
    q2           DECIMAL(10,4) NULL,
    q3           DECIMAL(10,4) NULL,
    q4           DECIMAL(10,4) NULL,
    q5           DECIMAL(10,4) NULL,
    q6           DECIMAL(10,4) NULL,
    q7           DECIMAL(10,4) NULL,
    q8           DECIMAL(10,4) NULL,
    q9           DECIMAL(10,4) NULL,
    q10          DECIMAL(10,4) NULL,
    trainingtime DECIMAL(10,4) NULL,
    PisteYear    NVARCHAR(10)  NULL,
    trainingsince NVARCHAR(50) NULL
);
GO

-- Main SOC evaluation summary per athlete/year
CREATE TABLE dbo.socadditionalvalues (
    id                      INT           NOT NULL PRIMARY KEY,
    toolenvironment         NVARCHAR(255) NULL,
    first_name              NVARCHAR(100) NULL,
    last_name               NVARCHAR(100) NULL,
    birthdate               DATE          NULL,
    trainingperf            NVARCHAR(50)  NULL,
    resilience              NVARCHAR(50)  NULL,
    PisteYear               NVARCHAR(10)  NULL,
    trainingsince           NVARCHAR(50)  NULL,
    trainingtime            NVARCHAR(50)  NULL,
    piste                   NVARCHAR(50)  NULL,
    competitions            NVARCHAR(50)  NULL,
    sex                     NVARCHAR(20)  NULL,
    quality                 NVARCHAR(50)  NULL,
    compenhancement         NVARCHAR(50)  NULL,
    totalpoints             NVARCHAR(50)  NULL,
    Category                NVARCHAR(100) NULL,
    pisteminregio           NVARCHAR(50)  NULL,
    pisteminnational        NVARCHAR(50)  NULL,
    CompPointsNationalTeam  NVARCHAR(50)  NULL,
    talentcard              NVARCHAR(50)  NULL,
    bioagevalue             NVARCHAR(50)  NULL,
    mirwaldvalue            NVARCHAR(50)  NULL,
    CompPointsRegionalTeam  NVARCHAR(50)  NULL
);
GO

-- Per-athlete, per-year injury flag used by SOC calculation and display
CREATE TABLE dbo.athleteyearstatus (
    id          INT           NOT NULL PRIMARY KEY,
    first_name  NVARCHAR(100) NULL,
    last_name   NVARCHAR(100) NULL,
    PisteYear   NVARCHAR(10)  NULL,
    injured     BIT           NULL
);
GO

-- ============================================================
-- Indexes for common query patterns
-- ============================================================

CREATE INDEX IX_athletes_name      ON dbo.athletes (last_name, first_name);
CREATE INDEX IX_athletes_category  ON dbo.athletes (category, sex);
CREATE INDEX IX_pisteresults_yr    ON dbo.pisteresults (TestYear, athlete_id);
CREATE INDEX IX_compresults_name   ON dbo.compresults (last_name, first_name, Discipline);
CREATE INDEX IX_socadditional_yr   ON dbo.socadditionalvalues (PisteYear, last_name, first_name);
CREATE INDEX IX_athleteyearstatus_yr_name ON dbo.athleteyearstatus (PisteYear, last_name, first_name);
GO
