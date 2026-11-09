"""Training dictations for learning a correction table: same terms as the standard set, but
different sentences and different voices (ryan, vivian), so rules learned here are tested on
audio they never saw. All names are fictional."""

TRAINING = {
    "t01": ("ryan", [], [
        ("Repeat imaging showed the penumbra had shrunk.", 1.0),
        ("Thrombectomy was not offered because of the delay.", 1.2),
        ("We gave tenecteplase in the emergency department.", 1.0),
        ("She still has mild aphasia and some right hemiparesis.", 1.1),
        ("Keep atorvastatin at the high dose.", 0),
    ]),
    "t02": ("vivian", [], [
        ("Levetiracetam was increased after the second seizure.", 1.1),
        ("Lacosamide can be added if the spells continue.", 1.2),
        ("The EEG was normal this time.", 1.0),
        ("Admit him to the epilepsy monitoring unit next week.", 1.0),
        ("Lorazepam is only for clusters.", 0),
    ]),
    "t03": ("ryan", [], [
        ("Topiramate caused tingling so we stopped it.", 1.0),
        ("Galcanezumab has cut her headache days in half.", 1.2),
        ("Rimegepant is her rescue medicine.", 1.0),
        ("We may try onabotulinumtoxinA in the autumn.", 0),
    ]),
    "t04": ("vivian", [], [
        ("Ocrelizumab infusions are due in March.", 1.1),
        ("Natalizumab was stopped because of the JC virus result.", 1.2),
        ("Ofatumumab is the backup plan.", 1.0),
        ("Oligoclonal bands were found in the CSF.", 1.0),
        ("This meets the McDonald criteria for multiple sclerosis.", 0),
    ]),
    "t05": ("ryan", [], [
        ("Pyridostigmine helps her ptosis by the afternoon.", 1.0),
        ("Plasmapheresis worked well last spring.", 1.2),
        ("IVIG is planned if she gets worse.", 1.0),
        ("Myasthenia gravis is confirmed by the acetylcholine antibodies.", 1.1),
        ("Her dysarthria has improved.", 0),
    ]),
    "t06": ("vivian", [], [
        ("Apixaban was held before the procedure.", 1.0),
        ("Andexanet alfa is stocked in the pharmacy.", 1.2),
        ("Idarucizumab reverses dabigatran within minutes.", 1.0),
        ("Nicardipine keeps the pressure under control.", 1.1),
        ("Atrial fibrillation was found on the monitor.", 0),
    ]),
    "t07": ("ryan", [], [
        ("Lecanemab requires regular MRI checks.", 1.1),
        ("Donanemab can be stopped once the amyloid clears.", 1.2),
        ("We will ask Dr. Patel about the trial.", 0),
    ]),
    "t08": ("vivian", [], [
        ("Evolocumab brought the LDL down quickly.", 1.0),
        ("Alirocumab is a reasonable alternative.", 1.2),
        ("Inclisiran is given twice a year.", 1.0),
        ("Keep rosuvastatin and ezetimibe as they are.", 1.0),
        ("Any PCSK9 inhibitor needs insurance approval.", 0),
    ]),
    "t09": ("ryan", [], [
        ("Riluzole is well tolerated.", 1.0),
        ("Edaravone infusions start next month.", 1.2),
        ("The nerve conduction study was normal.", 1.0),
        ("Fasciculations were seen on the EMG.", 1.0),
        ("This is likely amyotrophic lateral sclerosis.", 0),
    ]),
    "t10": ("vivian", [], [
        ("Guillain-Barré syndrome usually follows an infection.", 1.1),
        ("If symptoms come back after eight weeks, consider CIDP.", 1.2),
        ("IVIG was given over five days.", 0),
    ]),
    "t11": ("ryan", [], [
        ("Acetazolamide made her feel tired.", 1.0),
        ("Papilledema is getting better.", 1.2),
        ("Ophthalmology will repeat the visual fields.", 1.0),
        ("Idiopathic intracranial hypertension is the working diagnosis.", 1.0),
        ("Fundoscopy is due again in a month.", 0),
    ]),
    "t12": ("vivian", [], [
        ("The meta-analysis includes twelve trials.", 1.0),
        ("Our PROSPERO record needs an update.", 1.2),
        ("The IRB asked for a new consent form.", 1.0),
        ("Export the REDCap data on Friday.", 1.0),
        ("Dr. Okafor will review the protocol.", 0),
    ]),
    "t13": ("ryan", [], [
        ("The Quadlet file lives in the user config folder.", 1.0),
        ("Podman starts it at boot.", 1.2),
        ("ROCm was faster than Vulkan on this card.", 1.0),
        ("The SQLite file is backed up by a cron job.", 1.1),
        ("Tailscale handles the private network.", 0),
    ]),
    "t14": ("vivian", [], [
        ("Llama.cpp reads the GGUF model.", 1.0),
        ("The context window is set very large.", 1.2),
        ("Embeddings feed the RAG index.", 1.0),
        ("The MCP server speaks JSON.", 1.0),
        ("OAuth login works again.", 0),
    ]),
    "t15": ("ryan", [], [
        ("We stopped clobazam and", 1.0),
        ("started lamotrigine slowly.", 1.2),
        ("Labetalol was given", 0.9),
        ("for the blood pressure.", 0),
    ]),
    "t16": ("vivian", [], [
        ("Clevidipine is easier to titrate", 0.9),
        ("than labetalol.", 1.2),
        ("Tranexamic acid was not used.", 1.0),
        ("Dr. Nguyen and Dr. Lindqvist agreed.", 0),
    ]),
}
