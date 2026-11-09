"""The 16-clip standard test set: clinical and technical dictations, two voices.

Each clip: voice, the target terms we score (spelled as they should be written), and the
script as (fragment, pause after it in seconds). Terms come from three groups so the test
can tell them apart: in a typical vocabulary-hint list, only in a larger term library, and
in neither. All names are fictional.
"""

STANDARD = {
    "s01_stroke": ("aiden", ["aphasia", "hemiparesis", "penumbra", "middle cerebral artery", "tenecteplase",
                             "thrombectomy", "stent retriever", "atorvastatin", "transthoracic echocardiogram", "Okafor"], [
        ("She came in with sudden aphasia and right hemiparesis.", 1.1),
        ("CT perfusion showed a large penumbra in the left middle cerebral artery territory.", 1.3),
        ("We gave tenecteplase and moved straight to thrombectomy with a stent retriever.", 1.0),
        ("Start atorvastatin and get a transthoracic echocardiogram tomorrow.", 1.2),
        ("Please let Dr. Okafor know before rounds.", 0),
    ]),
    "s02_seizure": ("serena", ["levetiracetam", "EEG", "lacosamide", "epilepsy monitoring unit", "semiology", "lorazepam"], [
        ("He had a generalized seizure at home this morning.", 1.0),
        ("We loaded him with levetiracetam and he is back to baseline.", 1.2),
        ("If the EEG shows ongoing discharges, add lacosamide.", 1.1),
        ("Consider the epilepsy monitoring unit to clarify the semiology.", 1.0),
        ("Avoid lorazepam unless he seizes again.", 0),
    ]),
    "s03_migraine": ("aiden", ["topiramate", "rimegepant", "galcanezumab", "onabotulinumtoxinA", "Lindqvist"], [
        ("Her migraines are now weekly despite topiramate.", 1.0),
        ("Rimegepant works for the acute attacks.", 1.1),
        ("We will start galcanezumab as prevention.", 1.2),
        ("If that fails, onabotulinumtoxinA is the next step.", 1.0),
        ("Follow up with Dr. Lindqvist in the spring.", 0),
    ]),
    "s04_ms": ("serena", ["multiple sclerosis", "McDonald criteria", "lumbar puncture", "oligoclonal bands", "CSF",
                          "ocrelizumab", "natalizumab", "ofatumumab", "JC virus"], [
        ("New diagnosis of multiple sclerosis by the McDonald criteria.", 1.1),
        ("The lumbar puncture showed oligoclonal bands in the CSF.", 1.2),
        ("We discussed ocrelizumab and natalizumab,", 0.9),
        ("and she prefers ofatumumab because it is given at home.", 1.1),
        ("Check her JC virus antibody before we decide.", 0),
    ]),
    "s05_myasthenia": ("aiden", ["ptosis", "dysarthria", "acetylcholine", "myasthenia gravis", "pyridostigmine", "IVIG",
                                 "plasmapheresis", "Nguyen"], [
        ("Worsening ptosis and dysarthria over the past month.", 1.0),
        ("Acetylcholine receptor antibodies are positive, consistent with myasthenia gravis.", 1.2),
        ("Continue pyridostigmine and start IVIG today.", 1.0),
        ("If breathing worsens, move to plasmapheresis.", 1.1),
        ("Dr. Nguyen will see him on Friday.", 0),
    ]),
    "s06_anticoag": ("serena", ["apixaban", "atrial fibrillation", "intracerebral hemorrhage", "andexanet alfa",
                                "nicardipine", "dabigatran", "idarucizumab"], [
        ("She is on apixaban for atrial fibrillation.", 1.0),
        ("The head CT shows a small intracerebral hemorrhage.", 1.2),
        ("Give andexanet alfa now and keep the blood pressure low with nicardipine.", 1.1),
        ("Hold apixaban and recheck imaging in the morning.", 1.0),
        ("If she were on dabigatran we would give idarucizumab instead.", 0),
    ]),
    "s07_dementia": ("aiden", ["amyloid", "lecanemab", "donanemab", "MRI", "Patel"], [
        ("Memory decline over the last year with a positive amyloid scan.", 1.0),
        ("We discussed lecanemab and donanemab,", 0.9),
        ("including the risk of brain swelling and the need for regular MRI scans.", 1.2),
        ("Her husband will think it over.", 1.0),
        ("Recheck in clinic with Dr. Patel.", 0),
    ]),
    "s08_lipids": ("serena", ["LDL", "rosuvastatin", "ezetimibe", "PCSK9", "evolocumab", "alirocumab", "inclisiran"], [
        ("LDL is still high on rosuvastatin and ezetimibe.", 1.1),
        ("Add a PCSK9 inhibitor, either evolocumab or alirocumab.", 1.2),
        ("Inclisiran is an option if frequent injections are a problem.", 1.0),
        ("Repeat the lipid panel after the next dose.", 0),
    ]),
    "s09_als": ("aiden", ["fasciculations", "EMG", "nerve conduction study", "amyotrophic lateral sclerosis", "riluzole",
                          "edaravone", "ALS"], [
        ("Progressive weakness with brisk reflexes and fasciculations.", 1.0),
        ("The EMG and nerve conduction study support amyotrophic lateral sclerosis.", 1.3),
        ("We started riluzole and talked about edaravone.", 1.0),
        ("Refer him to the ALS clinic,", 0.8),
        ("and ask social work to call the family.", 0),
    ]),
    "s10_gbs": ("serena", ["Guillain-Barré syndrome", "IVIG", "CIDP"], [
        ("Ascending numbness and weakness after a stomach bug.", 1.0),
        ("The spinal fluid shows high protein with a normal cell count.", 1.1),
        ("This looks like Guillain-Barré syndrome.", 1.2),
        ("Start IVIG and check his vital capacity every few hours.", 1.0),
        ("If it relapses later, think about CIDP.", 0),
    ]),
    "s11_iih": ("aiden", ["fundoscopy", "papilledema", "MRI", "lumbar puncture", "idiopathic intracranial hypertension",
                          "acetazolamide", "ophthalmology"], [
        ("Young woman with daily headaches and blurred vision.", 1.0),
        ("Fundoscopy shows papilledema and the MRI is otherwise normal.", 1.2),
        ("Opening pressure on lumbar puncture was high.", 1.1),
        ("This fits idiopathic intracranial hypertension.", 1.0),
        ("Start acetazolamide and send her to ophthalmology.", 0),
    ]),
    "s12_research": ("serena", ["PROSPERO", "meta-analysis", "REDCap", "IRB", "Okafor"], [
        ("The protocol is registered on PROSPERO.", 1.0),
        ("We will run the meta-analysis with a random effects model.", 1.2),
        ("Data goes into REDCap,", 0.9),
        ("and the IRB approved the consent form last week.", 1.1),
        ("Dr. Okafor will check the risk of bias.", 0),
    ]),
    "s13_devops": ("aiden", ["podman", "Quadlet", "Tailscale", "tailnet", "Vulkan", "ROCm", "cron job", "SQLite"], [
        ("The podman Quadlet restarts the container after every reboot.", 1.0),
        ("Tailscale keeps the dashboard private to the tailnet.", 1.2),
        ("I moved the model to Vulkan because ROCm crashed under load.", 1.1),
        ("Next step is a cron job that backs up the SQLite database.", 0),
    ]),
    "s14_llm": ("serena", ["GGUF", "llama.cpp", "context window", "embeddings", "RAG", "MCP server", "JSON", "OAuth"], [
        ("The GGUF file is quantized to save memory.", 1.0),
        ("Llama.cpp loads it with a long context window.", 1.2),
        ("Embeddings for the RAG search come from a smaller model.", 1.0),
        ("The MCP server exposes the tools over JSON.", 1.1),
        ("OAuth tokens are stored outside the repository.", 0),
    ]),
    # Mid-sentence pauses, the hard case for cutting into pieces.
    "s15_midpause": ("aiden", ["EEG", "clobazam", "lamotrigine"], [
        ("The plan is,", 0.9),
        ("after the EEG,", 1.0),
        ("to taper clobazam slowly and", 1.1),
        ("switch to lamotrigine over a month.", 1.2),
        ("If seizures return,", 0.8),
        ("restart clobazam and call the epilepsy team.", 0),
    ]),
    "s16_midpause": ("serena", ["labetalol", "clevidipine", "tranexamic acid"], [
        ("We gave labetalol for the pressure and", 1.0),
        ("then switched to clevidipine because", 0.9),
        ("the target was not reached.", 1.2),
        ("Tranexamic acid was considered,", 0.9),
        ("but we decided against it.", 0),
    ]),
}
