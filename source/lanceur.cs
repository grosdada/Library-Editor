// Lanceur a icone des bibliotheques — Library Editor.
//
// Un .bat ne peut pas porter d icone. Ce petit programme la porte, et lance
// le .bat du MEME NOM pose a cote de lui : LANCER-LA-BIBLIOTHEQUE.exe lance
// LANCER-LA-BIBLIOTHEQUE.bat, « Preparer une bibliotheque.exe » lance
// « Preparer une bibliotheque.bat ». Le .bat reste la seule logique de
// lancement : on peut toujours le lire, le corriger, ou le lancer lui-meme.
//
// Compile par source/build.py avec le csc du .NET Framework 4 (present sur
// tout Windows 10 et 11) :  csc /target:winexe /win32icon:icone.ico lanceur.cs
using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Windows.Forms;

static class Lanceur
{
    [STAThread]
    static int Main()
    {
        string exe = Assembly.GetExecutingAssembly().Location;
        string dossier = Path.GetDirectoryName(exe);
        string bat = Path.Combine(dossier, Path.GetFileNameWithoutExtension(exe) + ".bat");
        if (!File.Exists(bat))
        {
            MessageBox.Show("Fichier introuvable :\n\n" + bat, "Bibliotheque",
                            MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
        string cmd = Environment.GetEnvironmentVariable("ComSpec");
        if (string.IsNullOrEmpty(cmd)) cmd = "cmd.exe";
        // Une console a elle, exactement comme un double-clic sur le .bat.
        ProcessStartInfo psi = new ProcessStartInfo(cmd, "/c \"\"" + bat + "\"\"");
        psi.WorkingDirectory = dossier;
        psi.UseShellExecute = true;
        Process.Start(psi);
        return 0;
    }
}
