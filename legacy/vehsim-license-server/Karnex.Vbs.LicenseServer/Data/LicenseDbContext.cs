using Microsoft.EntityFrameworkCore;

namespace Karnex.Vbs.LicenseServer.Data
{
    public class LicenseDbContext : DbContext
    {
        public LicenseDbContext(DbContextOptions<LicenseDbContext> options) : base(options) { }

        public DbSet<Customer> Customers => Set<Customer>();
        public DbSet<License> Licenses => Set<License>();
        public DbSet<Activation> Activations => Set<Activation>();

        protected override void OnModelCreating(ModelBuilder b)
        {
            b.Entity<Customer>().HasIndex(c => c.Name);

            b.Entity<License>().HasIndex(l => l.Serial).IsUnique();
            b.Entity<License>().HasIndex(l => l.Key).IsUnique();
            b.Entity<License>()
                .HasOne(l => l.Customer)
                .WithMany(c => c.Licenses)
                .HasForeignKey(l => l.CustomerId)
                .OnDelete(DeleteBehavior.Cascade);

            b.Entity<Activation>().HasIndex(a => new { a.LicenseId, a.MachineId }).IsUnique();
            b.Entity<Activation>()
                .HasOne(a => a.License)
                .WithMany(l => l.Activations)
                .HasForeignKey(a => a.LicenseId)
                .OnDelete(DeleteBehavior.Cascade);
        }
    }
}
