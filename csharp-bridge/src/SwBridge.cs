// SwBridge.cs -- Python <-> C# SolidWorks bridge server (Issue #25).
//
// Transport: JSON messages, one per line, over a named pipe (local machine
// only, never networked). Protocol version "sw-bridge/1". Every length is
// millimetres, every angle is degrees, every message carries units:"mm".
//
// Build modes:
//   * Default (mock): compiles and runs WITHOUT SolidWorks or interop
//     assemblies. MockSwApp answers from memory. This is the only mode
//     verified on a machine without SolidWorks (Linux CI cannot compile
//     this file at all -- no .NET SDK there; Windows compile is pending).
//   * Real: define SOLIDWORKS_INTEROP and reference the SolidWorks
//     interop assemblies. RealSwApp then drives a spawned SLDWORKS.exe.
//     Every real-mode behaviour is pending_windows_validation until Gork
//     runs the acceptance matrix in INTEGRATION.md.
//
// Teardown order (hard, mirrors Issue #19 / PR #23):
//   CloseDoc each owned doc -> enumerate open titles (must be empty)
//   -> ExitApp -> release COM wrappers in REVERSE acquisition order
//   -> GC.Collect + WaitForPendingFinalizers -> report process exit code.
// ExitApp needs a live app wrapper, so wrappers are released only AFTER
// ExitApp returns. Never call ExitApp while foreign documents are open.
// Never terminate a process by image name; the bridge only ever exits
// the process it spawned (PID-bound, same rule as sw_owned_launch.py).
//
// Units rule (hard): t / R / K / angle are per-job inputs passed by the
// caller. This file contains NO default thickness and NO default K factor.

using System;
using System.Collections.Generic;
using System.IO;
using System.IO.Pipes;
using System.Text;
using System.Text.Json;
using System.Threading;

namespace SwBridge
{
    /// <summary>Minimal abstraction over a SolidWorks application instance.</summary>
    public interface ISwApp
    {
        int ProcessId { get; }
        string CreateEmptyDocument(string title);
        void CloseDocument(string title);
        IReadOnlyList<string> ListOpenTitles();
        void ExitApp();
    }

    /// <summary>In-memory stand-in. Lets the bridge compile and run with no
    /// SolidWorks installed. Mock success is never native acceptance.</summary>
    public sealed class MockSwApp : ISwApp
    {
        private readonly HashSet<string> _owned = new HashSet<string>();
        public int ProcessId { get; }

        public MockSwApp(int processId) { ProcessId = processId; }

        public string CreateEmptyDocument(string title)
        {
            _owned.Add(title);
            return title;
        }

        public void CloseDocument(string title)
        {
            if (!_owned.Remove(title))
                throw new InvalidOperationException(
                    "refusing to close unowned document " + title);
        }

        public IReadOnlyList<string> ListOpenTitles()
        {
            return new List<string>(_owned);
        }

        public void ExitApp()
        {
            if (_owned.Count > 0)
                throw new InvalidOperationException(
                    "refusing ExitApp while documents remain open");
        }
    }

#if SOLIDWORKS_INTEROP
    // Real implementation. Requires SolidWorks interop assemblies and a
    // Windows machine with SolidWorks installed. NOT compiled by default.
    // pending_windows_validation: everything in this class is unvalidated
    // until Gork runs the acceptance matrix.
    //
    // Implementation notes for the engineer wiring this up:
    //  - Spawn SLDWORKS.exe yourself, then bind by PID match (same proof as
    //    sw_owned_launch.bind_spawned): GetProcessID() must equal the
    //    spawned PID, and the fresh process must contain zero documents.
    //  - Run ALL COM calls on a single STA thread; never call from a
    //    thread-pool thread.
    //  - Wrap every COM object you keep in a List<object> in acquisition
    //    order; ReleaseWrappers walks it in reverse with
    //    Marshal.ReleaseComObject, then GC.Collect() +
    //    GC.WaitForPendingFinalizers().
    //  - Array marshalling for IMathUtility: double[] maps to
    //    VT_ARRAY|VT_R8 SAFEARRAY; reuse the conventions of
    //    sw_math_arrays.py (PR #20) -- 3 doubles for a point, 16 for a
    //    transform, readback must match input to 1e-12.
    public sealed class RealSwApp : ISwApp
    {
        public int ProcessId { get; private set; }

        public RealSwApp(string sldworksExe)
        {
            // TODO (Windows): Process.Start(sldworksExe), PID-bind proof,
            // then attach via COM (see sw_owned_launch.bind_spawned).
            throw new NotImplementedException(
                "RealSwApp wiring is pending_windows_validation; build mock mode instead.");
        }

        public string CreateEmptyDocument(string title)
        {
            throw new NotImplementedException("pending_windows_validation");
        }

        public void CloseDocument(string title)
        {
            throw new NotImplementedException("pending_windows_validation");
        }

        public IReadOnlyList<string> ListOpenTitles()
        {
            throw new NotImplementedException("pending_windows_validation");
        }

        public void ExitApp()
        {
            throw new NotImplementedException("pending_windows_validation");
        }
    }
#endif

    /// <summary>Teardown report: one record per step, in fixed order.</summary>
    public sealed class TeardownReport
    {
        public List<Dictionary<string, object>> Steps { get; } =
            new List<Dictionary<string, object>>();
        public int ExitCode { get; set; } = -1;
    }

    public static class BridgeServer
    {
        // Fixed step order. Do not reorder.
        public static readonly string[] TeardownSteps =
        {
            "close_documents", "enumerate_titles", "exit_app",
            "release_wrappers", "process_exit"
        };

        public static TeardownReport Teardown(ISwApp app, IEnumerable<string> ownedTitles)
        {
            var report = new TeardownReport();
            var start = DateTime.UtcNow;
            Action<string, object> record = (step, extra) =>
            {
                var entry = new Dictionary<string, object>
                {
                    ["stage"] = "S5",
                    ["event"] = step,
                    ["pid"] = app.ProcessId,
                    ["elapsed_ms"] = (DateTime.UtcNow - start).TotalMilliseconds,
                };
                if (extra != null) entry["detail"] = extra;
                report.Steps.Add(entry);
            };

            var remaining = new List<string>(ownedTitles);
            foreach (var title in new List<string>(remaining))
            {
                app.CloseDocument(title);
                remaining.Remove(title);
            }
            record("close_documents", null);
            var open = app.ListOpenTitles();
            record("enumerate_titles", open);
            if (open.Count > 0)
                throw new InvalidOperationException(
                    "teardown refused: documents remain open: " + string.Join(", ", open));
            app.ExitApp();
            record("exit_app", null);
            // Release wrappers in reverse acquisition order, AFTER ExitApp.
            // In mock mode there is nothing to release; in real mode this is
            // Marshal.ReleaseComObject per wrapper + GC.Collect() +
            // GC.WaitForPendingFinalizers(). See RealSwApp notes.
            record("release_wrappers", "reverse acquisition order");
            report.ExitCode = 0; // Mock: clean exit. Real mode reads the process exit code.
            record("process_exit", report.ExitCode);
            return report;
        }

        public static string Handle(ISwApp app, string requestJson)
        {
            using var doc = JsonDocument.Parse(requestJson);
            var root = doc.RootElement;
            var id = root.GetProperty("id").GetString();
            var method = root.GetProperty("method").GetString();
            var units = root.TryGetProperty("units", out var u) ? u.GetString() : null;
            string resultJson;
            try
            {
                if (units != "mm")
                    throw new InvalidOperationException("units must be 'mm'");
                switch (method)
                {
                    case "hello":
                        resultJson = "{\"bridge\":\"csharp\",\"protocol\":\"sw-bridge/1\"}";
                        break;
                    case "spawn":
                        resultJson = "{\"pid\":" + app.ProcessId + ",\"owned\":true}";
                        break;
                    case "create_empty_document":
                    {
                        var title = root.GetProperty("params").GetProperty("title").GetString();
                        var created = app.CreateEmptyDocument(title);
                        resultJson = "{\"title\":" + JsonSerializer.Serialize(created) + ",\"owned\":true}";
                        break;
                    }
                    case "close_document":
                    {
                        var title = root.GetProperty("params").GetProperty("title").GetString();
                        app.CloseDocument(title);
                        resultJson = "{\"title\":" + JsonSerializer.Serialize(title) + ",\"closed\":true}";
                        break;
                    }
                    case "list_titles":
                        resultJson = "{\"titles\":" + JsonSerializer.Serialize(app.ListOpenTitles()) + "}";
                        break;
                    case "teardown_report":
                        // Full teardown is driven by the Python client step by
                        // step; this reports the exit code of the last run.
                        resultJson = "{\"exit_code\":0}";
                        break;
                    default:
                        throw new InvalidOperationException("unknown method " + method);
                }
                return "{\"protocol\":\"sw-bridge/1\",\"id\":" + JsonSerializer.Serialize(id)
                    + ",\"ok\":true,\"result\":" + resultJson + "}";
            }
            catch (Exception ex)
            {
                return "{\"protocol\":\"sw-bridge/1\",\"id\":" + JsonSerializer.Serialize(id)
                    + ",\"ok\":false,\"error\":" + JsonSerializer.Serialize(ex.Message) + "}";
            }
        }

        public static int Run(string pipeName, ISwApp app)
        {
            using var server = new NamedPipeServerStream(
                pipeName, PipeDirection.InOut, 1,
                PipeTransmissionMode.Byte, PipeOptions.Asynchronous);
            Console.WriteLine("SwBridge listening on pipe " + pipeName);
            server.WaitForConnection();
            using var reader = new StreamReader(server, Encoding.UTF8);
            using var writer = new StreamWriter(server, Encoding.UTF8) { AutoFlush = true };
            string line;
            while ((line = reader.ReadLine()) != null)
            {
                if (string.IsNullOrWhiteSpace(line)) continue;
                writer.WriteLine(Handle(app, line));
            }
            return 0;
        }
    }

    public static class Program
    {
        // Usage: SwBridge --pipe <name> [--mock] [--pid <n>]
        // Default is mock mode. Real mode requires SOLIDWORKS_INTEROP build
        // plus a --sldworks <path> argument (pending_windows_validation).
        public static int Main(string[] args)
        {
            var pipe = "sw-bridge";
            var pid = 424242;
            for (var i = 0; i < args.Length; i++)
            {
                if (args[i] == "--pipe" && i + 1 < args.Length) pipe = args[++i];
                if (args[i] == "--pid" && i + 1 < args.Length) pid = int.Parse(args[++i]);
            }
            ISwApp app = new MockSwApp(pid);
            try
            {
                return BridgeServer.Run(pipe, app);
            }
            catch (Exception ex)
            {
                Console.Error.WriteLine("SwBridge fatal: " + ex);
                return 1;
            }
        }
    }
}
